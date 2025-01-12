import json
from typing import Dict, TYPE_CHECKING

from requests import Response

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
import os
import logging
import warnings
from dotenv import load_dotenv

from src.prompts.classification_prompts import PARAMETER_CONSTRAINT_IDENTIFICATION_PREFIX, EXAMPLE_GENERATION_PROMPT, \
    MESSAGE_HEADER, PARAMETERS_HEADER, CONSTRAINT_EXTRACTION_PREFIX, FEW_SHOT_CLASSIFICATON_PREFIX, \
    CLASSIFICATION_SUFFIX, EXTRACT_PARAMETER_DEPENDENCIES
from src.utils import OpenAILanguageModel
from src.graph.specification_parser import SchemaProperties, ParameterProperties

def configure_response_logging():
    logging_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logging_dir, exist_ok=True)
    run_number = 1
    while os.path.exists(os.path.join(logging_dir, f"response_log{run_number}.log")):
        run_number += 1
    log_file = os.path.join(logging_dir, f"response_log{run_number}.log")
    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Logging started")

#warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
load_dotenv() # load environmental vars for OpenAI API key
#configure_response_logging()

if TYPE_CHECKING:
    from src.generate_graph import OperationNode, OperationEdge
    from src.request_generator import RequestGenerator, RequestData, RequestResponse

class ResponseHandler:
    def __init__(self):
        self.parser_type = "html.parser"
        self.language_model = ResponseLanguageModelHandler("OPENAI")

    def extract_response_text(self, response: Response):
        if response is None:
            raise ValueError("Empty response during response handling. Response value is: ", response)
        response_text = response.text
        #TODO handle JS responses
        result = ' '.join(BeautifulSoup(response_text, self.parser_type).stripped_strings) # process HTML response
        logging.info(f"Extracted response text: {result}")
        return result

    def classify_error(self, response: Response, response_text: str):
        return self.language_model.classify_response(response_text) 
    
    def _is_valid_dependency(self, failed_response: Response, tentative_response: Response):
        if failed_response is None or tentative_response is None:
            return False
        if failed_response.status_code // 100 == 2:
            return True
        return False
    
    def handle_operation_dependency_error(self, request_generator: 'RequestGenerator', failed_operation_node: 'OperationNode'):
        '''
        Handle the operation dependency error by trying tentative edges.
        '''
        # TODO: Figure out how to handle tentative edges in response-param vs param-param
        if not failed_operation_node.tentative_edges:
            return
        sorted_edges = sorted(failed_operation_node.tentative_edges, key=lambda x: list(x.similar_parameters.values())[0].similarity, reverse=True) # sort tentative edges by their one parameter similarity value
        print(f"Handling operation dependency error for operation {failed_operation_node.operation_properties.operation_id}")
        for tentative_edge in sorted_edges:
            if request_generator.handle_tentative_dependency(tentative_edge=tentative_edge, failed_operation_node=failed_operation_node):
                return

    def handle_parameter_constraint_error(self, response_text: str, parameters: Dict[str, 'SchemaProperties']):
        if parameters:
            modified_parameter_schemas = self.language_model.extract_constrained_schemas(response_text, parameters)
            if modified_parameter_schemas:
                for parameter in parameters:
                    if parameter in modified_parameter_schemas:
                        print(f"Updating parameter {parameter} with new schema")
                        logging.info(f"Updating parameter {parameter} with new schema")
                        logging.info(f"New schema: {modified_parameter_schemas[parameter]}")
                        parameters[parameter] = modified_parameter_schemas[parameter]

    def handle_format_constraint_error(self, response_text: str, parameters: Dict[str, 'SchemaProperties']):
        if parameters:
            parameter_format_examples = self.language_model.extract_parameter_formatting(response_text, parameters)
            if parameter_format_examples:
                for parameter in parameters:
                    if parameter in parameter_format_examples:
                        print(f"Updating parameter {parameter} with new example value {parameter_format_examples[parameter]}")
                        logging.info(f"Updating parameter {parameter} with new example value {parameter_format_examples[parameter]}")
                        parameters[parameter].example = parameter_format_examples[parameter]

    def handle_parameter_dependency_error(self, response_text: str, parameters: Dict[str, 'SchemaProperties']):
        if parameters:
            required_parameters = self.language_model.extract_parameter_dependency(response_text, parameters)
            if required_parameters:
                for parameter in parameters:
                    if parameter in required_parameters:
                        print(f"Updating parameter {parameter} to required")
                        logging.info(f"Updating parameter {parameter} to required")
                        parameters[parameter].required = True

    def handle_error(self, response: Response, operation_node: 'OperationNode', request_data: 'RequestData', request_generator: 'RequestGenerator'):
        response_text = self.extract_response_text(response)
        error_classification = self.classify_error(response, response_text)
        query_parameters: Dict[str, 'ParameterProperties'] = request_data.operation_properties.parameters

        request_body: Dict[str, 'SchemaProperties'] = request_data.operation_properties.request_body
        simplified_parameters: Dict[str, 'SchemaProperties'] = {parameter: properties.schema for parameter, properties in query_parameters.items()}

        #logging.info(f"Classified error as: {error_classification}, has request body: {request_body} and query parameters: {simplified_parameters}")
        #print(f"Classified error as: {error_classification}, has request body: {request_body} and query parameters: {simplified_parameters}")
        # REMINDER: parameters = Dict[str, ParameterProperties] -> schema = SchemaProperties
        # REMINDER: request_body = Dict[str, SchemaProperties]
        if error_classification == "PARAMETER CONSTRAINT":
            #identify parameter constraint and return new parameters and request body dictionary that specifies the parameters to use
            self.handle_parameter_constraint_error(response_text, simplified_parameters)
            self.handle_parameter_constraint_error(response_text, request_body)
        elif error_classification == "FORMAT":
            #should return map from parameter -> example
            self.handle_format_constraint_error(response_text, simplified_parameters)
            self.handle_format_constraint_error(response_text, request_body)
        elif error_classification == "PARAMETER DEPENDENCY":
            self.handle_parameter_dependency_error(response_text, simplified_parameters)
            self.handle_parameter_dependency_error(response_text, request_body)
        elif error_classification == "OPERATION DEPENDENCY":
            self.handle_operation_dependency_error(request_generator, operation_node)
        else:
            return None

class ResponseLanguageModelHandler:
    def __init__(self, language_model="OPENAI"):
        if language_model == "OPENAI":
            self.language_model = OpenAILanguageModel()
        else:
            raise ValueError("Language model not supported")

    def _extract_classification(self, response_text: str):
        classification = None
        if response_text is None:
            return classification
        if "PARAMETER CONSTRAINT" in response_text:
            classification = "PARAMETER CONSTRAINT"
        elif "FORMAT" in response_text:
            classification = "FORMAT"
        elif "PARAMETER DEPENDENCY" in response_text:
            classification = "PARAMETER DEPENDENCY"
        elif "OPERATION DEPENDENCY" in response_text:
            classification = "OPERATION DEPENDENCY"
        return classification

    def _extract_constrained_parameter_list(self, language_model_response):
        if "IDENTIFICATION:" not in language_model_response:
            return None
        elif language_model_response.strip() == 'IDENTIFICATION:' or language_model_response.strip() == 'IDENTIFICATION: none':
            return None
        else:
            return language_model_response.split("IDENTIFICATION:")[1].strip().split(",")

    def _extract_parameters_to_constrain(self, response_text: str, request_params):
        parameter_list = [parameter for parameter in request_params]
        #create a comma seperated string of parameters
        parameters = ",".join(parameter_list)
        parameters = "PARAMETERS: " + parameters + "\n"
        message = "MESSAGE: " + response_text + "\n"

        llm_query_response = self.language_model.query(user_message=PARAMETER_CONSTRAINT_IDENTIFICATION_PREFIX + message + parameters)
        logging.info(f"Extracted parameters to constrain: {llm_query_response}")
        extracted_parameter_list = self._extract_constrained_parameter_list(llm_query_response)
        #return self._extract_constrained_parameter_list(extracted_paramter_list)
        return extracted_parameter_list

    def _generate_parameter_value(self, parameters_to_generate_for, response_text: str):
        example_value_map = {}
        for parameter in parameters_to_generate_for:
            raw_result = self.language_model.query(user_message=EXAMPLE_GENERATION_PROMPT + MESSAGE_HEADER + response_text + PARAMETERS_HEADER + parameter)
            #parse the result to get the example value
            example_value = raw_result.split("EXAMPLE:")[1].strip()
            example_value_map[parameter] = example_value
        return example_value_map

    def define_constrained_schema(self, parameter, response_text: str):
        extract_query = CONSTRAINT_EXTRACTION_PREFIX + MESSAGE_HEADER + response_text + PARAMETERS_HEADER + parameter

        json_schema_properties = self.language_model.query(user_message=extract_query, json_mode=True)
        #read the json string into a dictionary
        schema_properties = json.loads(json_schema_properties)
        #map it to a schema properties dataclass, ensure checking of failures and only map what is possible
        schema = SchemaProperties()
        for key, value in schema_properties.items():
            if hasattr(schema, key):
                setattr(schema, key, value)
        return schema

    def extract_constrained_schemas(self, response_text: str, request_params):
        """
        Find the parameters that need to be constrained, then processes constraints
        :param response_text:
        :param request_params:
        :return:
        """
        parameters_to_constrain = self._extract_parameters_to_constrain(response_text, request_params)
        constrained_schemas = {}
        if parameters_to_constrain:
            for parameter in parameters_to_constrain:
                if parameter in request_params:
                    constrained_schemas[parameter] = self.define_constrained_schema(parameter, response_text)
        return constrained_schemas

    def classify_response(self, response_text: str):
        return self._extract_classification(self.language_model.query(user_message=FEW_SHOT_CLASSIFICATON_PREFIX + response_text + CLASSIFICATION_SUFFIX))

    def extract_parameter_formatting(self, response_text: str, request_params):
        params_list = self._extract_parameters_to_constrain(response_text, request_params) #this can be none
        if params_list is not None:
            return self._generate_parameter_value(params_list, response_text)
        else:
            return None

    def extract_parameter_dependency(self, response_text: str, request_params):
        list_of_request_parameters = [parameter for parameter in request_params]
        parameters = ",".join(list_of_request_parameters)
        parameters = "PARAMETERS: " + parameters + "\n"
        message = "MESSAGE: " + response_text + "\n"
        extracted_paramter_list = self._extract_constrained_parameter_list(self.language_model.query(user_message=EXTRACT_PARAMETER_DEPENDENCIES + message + parameters))
        #clean the response
        if extracted_paramter_list is None:
            return None
        else:
            return set(extracted_paramter_list.split("DEPENDENCIES: ")[1].strip().split(","))

class DummyRequest:
    def __init__(self):
        self.response = 'if email is provided age must be set'

class DummySchema :
    def __init__(self):
        pass
