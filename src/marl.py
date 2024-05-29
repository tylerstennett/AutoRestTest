import copy
import json
import os
import random
import time
from collections import defaultdict

import requests
import shelve

from src.generate_graph import OperationGraph
from src.graph.specification_parser import OperationProperties
from src.reinforcement.agents import OperationAgent, HeaderAgent, ParameterAgent, ValueAgent, ValueAction, BodyObjAgent, \
    DataSourceAgent, DependencyAgent
from src.utils import _construct_db_dir, construct_basic_token, get_nested_obj_mappings, process_body_params
from src.value_generator import identify_generator, randomize_string, random_generator, randomize_object


class QLearning:
    def __init__(self, operation_graph, alpha=0.1, gamma=0.9, epsilon=0.3, time_duration=600, mutation_rate=0.3):
        self.q_table = {}
        self.operation_graph: OperationGraph = operation_graph
        self.api_url = operation_graph.request_generator.api_url
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.mutation_rate = mutation_rate
        self.operation_agent = OperationAgent(operation_graph, alpha, gamma, 0.4)
        self.header_agent = HeaderAgent(operation_graph, alpha, gamma, epsilon)
        self.parameter_agent = ParameterAgent(operation_graph, alpha, gamma, 0.4)
        self.value_agent = ValueAgent(operation_graph, alpha, gamma, epsilon)
        self.body_object_agent = BodyObjAgent(operation_graph, alpha, gamma, epsilon)
        self.data_source_agent = DataSourceAgent(operation_graph, alpha, gamma, epsilon)
        self.dependency_agent = DependencyAgent(operation_graph, alpha, gamma, epsilon)
        self.time_duration = time_duration
        self.responses = defaultdict(int)

    def initialize_llm_agents(self):
        self.header_agent.initialize_q_table()
        self.value_agent.initialize_q_table()

    def print_q_tables(self):
        print("OPERATION Q-TABLE: ", self.operation_agent.q_table)
        print("HEADER Q-TABLE: ", self.header_agent.q_table)
        print("PARAMETER Q-TABLE: ", self.parameter_agent.q_table)
        print("VALUE Q-TABLE: ", self.value_agent.q_table)

    def get_mapping(self, select_params, select_values):
        if not select_params:
            return None
        mapping = {}
        for i in range(len(select_params)):
            if select_params[i] in select_values:
                mapping[select_params[i]] = select_values[select_params[i]]
        return mapping

    def get_mutated_value(self, param_type):
        if not param_type:
            return None
        avail_types = ["integer", "number", "string", "boolean", "array", "object"]
        avail_types.remove(param_type)
        select_type = random.choice(avail_types)
        return identify_generator(select_type)()

    def mutate_values(self, operation_properties: OperationProperties, parameters, body, header):

        avail_medias = ["application/json", "application/x-www-form-urlencoded", "multipart/form-data", "text/plain"]
        avail_methods = ["get", "post", "put", "delete", "patch"]

        individual_mutation_rate = 0.5
        method_mutate_rate = 0.1
        media_mutate_rate = 0.1
        parameter_selection_mutate_rate = 0.4
        token_mutation_rate = 0.2

        specific_method = None
        if operation_properties.http_method and random.random() < method_mutate_rate and operation_properties.http_method.lower() in avail_methods:
            avail_methods.remove(operation_properties.http_method.lower())
            specific_method = random.choice(avail_methods)

        if random.random() < token_mutation_rate:
            random_token_params = {"username": randomize_string(), "password": randomize_string()}
            header = {"Authorization": construct_basic_token(random_token_params)}

        mutated_parameter_names = False
        if random.random() < parameter_selection_mutate_rate:
            mutated_parameter_names = True
            parameters = {randomize_string(): random_generator()() for _ in range(random.randint(2,6))}

        if operation_properties.parameters and parameters:
            for parameter_name, parameter_properties in operation_properties.parameters.items():
                if parameter_name in parameters:
                    if parameter_properties.schema and random.random() < individual_mutation_rate:
                        parameters[parameter_name] = self.get_mutated_value(parameter_properties.schema.type)
                    if parameters[parameter_name] is None:
                        parameters.pop(parameter_name, None)

        if operation_properties.request_body and body:
            for mime, body_properties in operation_properties.request_body.items():
                if mime in body and random.random() < individual_mutation_rate:
                    if random.random() < 0.5:
                        body[mime] = self.get_mutated_value(body_properties.type)
                    else:
                        body[mime] = randomize_object()
                if body[mime] is None:
                    body.pop(mime, None)

        if random.random() < media_mutate_rate and body:
            for media in body.keys():
                avail_medias.remove(media)
            if avail_medias and random.random() < individual_mutation_rate:
                new_body = {random.choice(avail_medias): body.popitem()[1]}
                body = new_body

        return parameters, body, header, specific_method, mutated_parameter_names

    def send_operation(self, operation_properties: OperationProperties, parameters, body, header, specific_method=None):
        endpoint_path = operation_properties.endpoint_path
        http_method = specific_method if specific_method else operation_properties.http_method.lower()
        processed_parameters = copy.deepcopy(parameters)

        if processed_parameters:
            for parameter_name, parameter_properties in operation_properties.parameters.items():
                if parameter_properties.in_value == "path" and parameter_name in processed_parameters:
                    path_value = processed_parameters[parameter_name]
                    endpoint_path = endpoint_path.replace("{" + parameter_name + "}", str(path_value))
                    processed_parameters.pop(parameter_name, None)

        try:
            select_method = getattr(requests, http_method)
            full_url = self.api_url + endpoint_path
            print("SENDING REQUEST TO OPERATION: ", operation_properties.operation_id)
            print("PARAMETERS: ", processed_parameters)
            print("BODY: ", body)
            print("HEADER: ", header)
            if body:
                if not header:
                    header = {}
                if "application/json" in body:
                    header["Content-Type"] = "application/json"
                    response = select_method(full_url, params=processed_parameters, json=body["application/json"], headers=header)
                elif "application/x-www-form-urlencoded" in body: # mime_type == "application/x-www-form-urlencoded":
                    header["Content-Type"] = "application/x-www-form-urlencoded"
                    body_data = get_nested_obj_mappings(body["application/x-www-form-urlencoded"])
                    if not body_data or not isinstance(body_data, dict):
                        body_data = {"data": body["application/x-www-form-urlencoded"]}
                    body["application/x-www-form-urlencoded"] = body_data
                    response = select_method(full_url, params=processed_parameters, data=body["application/x-www-form-urlencoded"], headers=header)
                elif "multipart/form-data" in body:
                    header["Content-Type"] = "multipart/form-data"
                    file = {"file": ("file.txt", json.dumps(body["multipart/form-data"]).encode('utf-8'), "application/json"),
                            "metadata": (None, "metadata")}
                    body["multipart/form-data"] = file
                    response = select_method(full_url, params=processed_parameters, files=body["multipart/form-data"], headers=header)
                else: # mime_type == "text/plain":
                    header["Content-Type"] = "text/plain"
                    if not isinstance(body["text/plain"], str):
                        body["text/plain"] = str(body["text/plain"])
                    response = select_method(full_url, params=processed_parameters, data=body["text/plain"], headers=header)
            else:
                response = select_method(full_url, params=processed_parameters, headers=header)

            return response
        except requests.exceptions.RequestException as err:
            print(f"Error with operation {operation_properties.operation_id}: {err}")
            return None
        except Exception as err:
            print(f"Unexpected error with operation {operation_properties.operation_id}: {err}")
            print("Parameters: ", processed_parameters)
            print("Body: ", body)
            return None

    def determine_header_reward(self, response):
        if response is None:
            return -10
        status_code = response.status_code
        if status_code == 401:
            return -3
        elif status_code // 100 == 4:
            return -1
        elif status_code // 100 == 5:
            return -1
        elif status_code // 100 == 2:
            return 2
        else:
            return -3

    def determine_value_response_reward(self, response):
        if response is None:
            return -10
        status_code = response.status_code
        if status_code // 100 == 2:
            return 2
        elif status_code == 405:
            return -5
        elif status_code // 100 == 4:
            return -2
        elif status_code // 100 == 5:
            return -1
        else:
            return -5

    def determine_parameter_response_reward(self, response):
        if response is None:
            return -10
        status_code = response.status_code
        if status_code // 100 == 2:
            return 2
        elif status_code == 405:
            return -5
        elif status_code // 100 == 4:
            return -2
        elif status_code // 100 == 5:
            return -1
        else:
            return -5

    def determine_good_response_reward(self, response):
        if response is None:
            return -10
        status_code = response.status_code
        if status_code // 100 == 2:
            return 2
        elif status_code == 405:
            return -3
        elif status_code // 100 == 4:
            return -1
        elif status_code // 100 == 5:
            return -1
        else:
            return -5

    def determine_bad_response_reward(self, response):
        if response is None:
            return -10
        status_code = response.status_code
        if status_code == 405:
            return -10
        elif status_code == 401:
            return -3
        elif status_code // 100 == 4:
            return 1
        elif status_code // 100 == 5:
            return 2
        elif status_code // 100 == 2:
            return -1
        else:
            return -5

    def _init_parameter_tracking(self, successful_parameters):
        for operation_id, operation_node in self.operation_graph.operation_nodes.items():
            if operation_id not in successful_parameters:
                successful_parameters[operation_id] = {}
            if operation_node.operation_properties.parameters:
                for parameter_name in operation_node.operation_properties.parameters.keys():
                    successful_parameters[operation_id][parameter_name] = []

    def _init_body_tracking(self, successful_bodies):
        for operation_id, operation_node in self.operation_graph.operation_nodes.items():
            if operation_id not in successful_bodies:
                successful_bodies[operation_id] = {}
            if operation_node.operation_properties.request_body:
                for mime_type, body_properties in operation_node.operation_properties.request_body.items():
                    body_params = process_body_params(body_properties)
                    successful_bodies[operation_id] = {param: [] for param in body_params}

    def _init_response_tracking(self, successful_responses):
        for operation_id, operation_node in self.operation_graph.operation_nodes.items():
            if operation_id not in successful_responses:
                successful_responses[operation_id] = {}
            if operation_node.operation_properties.responses:
                for response_type, response_properties in operation_node.operation_properties.responses.items():
                    if response_properties.content:
                        for response, response_details in response_properties.content.items():
                            response_params = process_body_params(response_details)
                            successful_responses[operation_id] = {param: [] for param in response_params}

    def _construct_body_property(self, body_property, unconstructed_body):
        if body_property.type == "object":
            return {prop: val for prop, val in unconstructed_body.items() if prop in body_property.properties}
        elif body_property.type == "array":
            return [self._construct_body_property(body_property.items, unconstructed_body)]
        else:
            return None

    def _construct_body(self, unconstructed_body, operation_id, mime_type):
        op_props = self.operation_graph.operation_nodes[operation_id].operation_properties
        for mime, body_properties in op_props.request_body.items():
            if mime == mime_type:
                return self._construct_body_property(body_properties, unconstructed_body)

    def _deconstuct_obj(self, body):
        if body is None:
            return None
        if type(body) == dict:
            return {prop: val for prop, val in body.items()}
        elif type(body) == list:
            return self._deconstuct_obj(body[0])
        else:
            return None

    def generate_default_values(self, operation_id):
        parameters = {}
        if self.operation_graph.operation_nodes[operation_id].operation_properties.parameters:
            for parameter_name, parameter_properties in self.operation_graph.operation_nodes[operation_id].operation_properties.parameters.items():
                if parameter_properties.schema:
                    parameters[parameter_name] = identify_generator(parameter_properties.schema.type)()
        body = {}
        if self.operation_graph.operation_nodes[operation_id].operation_properties.request_body:
            for mime_type, body_properties in self.operation_graph.operation_nodes[operation_id].operation_properties.request_body.items():
                body[mime_type] = identify_generator(body_properties.type)()
        return parameters, body

    def execute_operations(self, successful_parameters, successful_bodies, successful_responses):
        start_time = time.time()

        while time.time() - start_time < self.time_duration:
            print(f"Responses: {self.responses}")
            print("TIME REMAINING: ", self.time_duration - (time.time() - start_time))
            operation_id = self.operation_agent.get_action()
            #operation_id = random.choice(list(self.operation_graph.operation_nodes.keys()))

            select_params = self.parameter_agent.get_action(operation_id)
            select_header = self.header_agent.get_action(operation_id)

            if time.time() - start_time > 30:
                data_source = self.data_source_agent.get_action(operation_id)
            else:
                data_source = "WAITING"

            print("SENDING TO OPERATION: ", operation_id)
            print("SELECTED PARAMS: ", select_params.req_params)
            print("SELECTED BODY: ", select_params.mime_type)

            parameter_dependencies, request_body_dependencies, unconstructed_body, select_values = None, None, {}, None
            if data_source == "WAITING":
                if random.random() < 0.2:
                    param_mappings, body_mappings = self.generate_default_values(operation_id)
                    parameters = self.get_mapping(select_params.req_params,
                                                  param_mappings) if select_params.req_params else None
                    body = self.get_mapping([select_params.mime_type],
                                            body_mappings) if select_params.mime_type else None
                else:
                    select_values = self.value_agent.get_action(operation_id)
                    parameters = self.get_mapping(select_params.req_params,
                                                  select_values.param_mappings) if select_params.req_params else None
                    body = self.get_mapping([select_params.mime_type],
                                            select_values.body_mappings) if select_params.mime_type else None
            elif data_source == "LLM":
                select_values = self.value_agent.get_action(operation_id)
                parameters = self.get_mapping(select_params.req_params, select_values.param_mappings) if select_params.req_params else None
                body = self.get_mapping([select_params.mime_type], select_values.body_mappings) if select_params.mime_type else None
            elif data_source == "DEFAULT":
                param_mappings, body_mappings = self.generate_default_values(operation_id)
                parameters = self.get_mapping(select_params.req_params, param_mappings) if select_params.req_params else None
                body = self.get_mapping([select_params.mime_type], body_mappings) if select_params.mime_type else None
            elif data_source == "DEPENDENCY":
                parameter_dependencies, request_body_dependencies = self.dependency_agent.get_action(operation_id)
                llm_select_values = self.value_agent.get_action(operation_id)
                llm_parameters = self.get_mapping(select_params.req_params,
                                              llm_select_values.param_mappings) if select_params.req_params else None
                llm_body = self.get_mapping([select_params.mime_type],
                                        llm_select_values.body_mappings) if select_params.mime_type else None

                parameters = {}
                if select_params.req_params:
                    for parameter, dependency in parameter_dependencies.items():
                        if parameter in select_params.req_params:
                            if dependency["in_value"] == "params" and dependency["dependent_operation"] in successful_parameters and dependency["dependent_val"] in successful_parameters[dependency["dependent_operation"]]:
                                if successful_parameters[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    parameters[parameter] = random.choice(successful_parameters[dependency["dependent_operation"]][dependency["dependent_val"]])

                            elif dependency["in_value"] == "body" and dependency["dependent_operation"] in successful_bodies and dependency["dependent_val"] in successful_bodies[dependency["dependent_operation"]]:
                                if successful_bodies[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    parameters[parameter] = random.choice(successful_bodies[dependency["dependent_operation"]][dependency["dependent_val"]])

                            elif dependency["in_value"] == "response" and dependency["dependent_operation"] in successful_responses and dependency["dependent_val"] in successful_responses[dependency["dependent_operation"]]:
                                if successful_responses[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    parameters[parameter] = random.choice(successful_responses[dependency["dependent_operation"]][dependency["dependent_val"]])
                    for param in select_params.req_params:
                        if param not in parameters:
                            parameters[param] = llm_parameters[param] if llm_parameters and param in llm_parameters else random_generator()()

                body = {}
                if select_params.mime_type and select_params.mime_type in self.operation_graph.operation_nodes[operation_id].operation_properties.request_body:
                    unconstructed_body = {}
                    possible_body_properties = process_body_params(self.operation_graph.operation_nodes[operation_id].operation_properties.request_body[select_params.mime_type])
                    for body_property, dependency in request_body_dependencies.items():
                        if body_property in possible_body_properties:
                            if dependency["in_value"] == "params" and dependency["dependent_operation"] in successful_parameters and dependency["dependent_val"] in successful_parameters[dependency["dependent_operation"]]:
                                if successful_parameters[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    unconstructed_body[body_property] = random.choice(successful_parameters[dependency["dependent_operation"]][dependency["dependent_val"]])

                            elif dependency["in_value"] == "body" and dependency["dependent_operation"] in successful_bodies and dependency["dependent_val"] in successful_bodies[dependency["dependent_operation"]]:
                                if successful_bodies[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    unconstructed_body[body_property] = random.choice(successful_bodies[dependency["dependent_operation"]][dependency["dependent_val"]])

                            elif dependency["in_value"] == "response" and dependency["dependent_operation"] in successful_responses and dependency["dependent_val"] in successful_responses[dependency["dependent_operation"]]:
                                if successful_responses[dependency["dependent_operation"]][dependency["dependent_val"]]:
                                    unconstructed_body[body_property] = random.choice(successful_responses[dependency["dependent_operation"]][dependency["dependent_val"]])

                    deconstructed_llm_body = self._deconstuct_obj(llm_body[select_params.mime_type]) if llm_body and select_params.mime_type in llm_body else None
                    if deconstructed_llm_body:
                        for prop in possible_body_properties:
                            if prop not in unconstructed_body:
                                unconstructed_body[prop] = deconstructed_llm_body[prop] if prop in deconstructed_llm_body else random_generator()()
                    body = {select_params.mime_type: self._construct_body(unconstructed_body, operation_id, select_params.mime_type)}
            else:
                parameters = None
                body = None

            header = {"Authorization": select_header} if select_header else None

            all_select_properties = {}
            if body:
                for mime, body_properties in body.items():
                    if type(body_properties) == dict:
                        select_properties = self.body_object_agent.get_action(operation_id, mime)
                        deconstructed_body = self._deconstuct_obj(body_properties)
                        if select_properties:
                            new_bodies_properties = {prop: deconstructed_body[prop] for prop in deconstructed_body if prop in select_properties}
                            body[mime] = new_bodies_properties
                        else:
                            body[mime] = None
                        all_select_properties[mime] = select_properties

            # Mutate operation values
            mutate_operation = random.random() < self.mutation_rate
            mutated_parameter_names = False
            if mutate_operation:
                parameters, body, header, specific_method, mutated_parameter_names = self.mutate_values(self.operation_graph.operation_nodes[operation_id].operation_properties, parameters, body, header)
                response = self.send_operation(self.operation_graph.operation_nodes[operation_id].operation_properties, parameters, body, header, specific_method)
            else:
                response = self.send_operation(self.operation_graph.operation_nodes[operation_id].operation_properties, parameters, body, header)

            # Only update table when using table values (so not mutated)
            if not mutate_operation:
                self.parameter_agent.update_q_table(operation_id, select_params, self.determine_parameter_response_reward(response))
                self.header_agent.update_q_table(operation_id, select_header, self.determine_header_reward(response))
                self.operation_agent.update_q_table(operation_id, self.determine_bad_response_reward(response))

                # For the first thirty seconds, do not update data source table (to account for minimal filled dependencies)
                if data_source != "WAITING":
                    self.data_source_agent.update_q_table(operation_id, data_source, self.determine_good_response_reward(response))

                # If body object agent is used, update the q-table
                if all_select_properties:
                    for mime, select_properties in all_select_properties.items():
                        self.body_object_agent.update_q_table(operation_id, mime, select_properties, self.determine_good_response_reward(response))

                # Update dependency agent if dependency data source
                if data_source == "DEPENDENCY":
                    used_dependent_params = {}
                    if parameter_dependencies:
                        for parameter in parameters:
                            if parameter in select_params.req_params and parameter in parameter_dependencies:
                                used_dependent_params[parameter] = parameter_dependencies[parameter]
                    used_dependent_body = {}
                    if request_body_dependencies and unconstructed_body and all_select_properties[select_params.mime_type]:
                        for body_param in unconstructed_body:
                            if body_param in all_select_properties[select_params.mime_type] and body_param in request_body_dependencies:
                                used_dependent_body[body_param] = request_body_dependencies[body_param]
                    self.dependency_agent.update_q_table(operation_id, used_dependent_params, used_dependent_body, self.determine_good_response_reward(response))
                elif data_source == "LLM" and select_values is not None:
                    # Update LLM value agent if LLM data source
                    processed_value_action = ValueAction(param_mappings=parameters, body_mappings=select_values.body_mappings)
                    self.value_agent.update_q_table(operation_id, processed_value_action,
                                                    self.determine_value_response_reward(response))

            # Update successful parameters to use for future operation dependencies
            if response is not None and response.ok and not mutated_parameter_names:
                if parameters and successful_parameters[operation_id]:
                    for param_name, param_val in parameters.items():
                        if param_name in successful_parameters[operation_id] and param_val not in successful_parameters[operation_id][param_name]:
                            successful_parameters[operation_id][param_name].append(param_val)
                if body and successful_bodies[operation_id]:
                    for mime, body_properties in body.items():
                        deconstructed_body = self._deconstuct_obj(body_properties)
                        if deconstructed_body:
                            for prop_name, prop_val in deconstructed_body.items():
                                if prop_name in successful_bodies[operation_id] and prop_val not in successful_bodies[operation_id][prop_name]:
                                    successful_bodies[operation_id][prop_name].append(prop_val)
                if response.content and successful_responses[operation_id]:
                    try:
                        response_content = json.loads(response.content)
                    except json.JSONDecodeError:
                        response_content = None

                    deconstructed_responses = []
                    if response_content and type(response_content) == list:
                        deconstructed_responses = [self._deconstuct_obj(response_obj) for response_obj in response_content]
                    elif response_content:
                        deconstructed_responses = [self._deconstuct_obj(response_content)]
                        if self._deconstuct_obj(response_content) is None:
                            print("RESPONSE CONTENT WITH NONE: ", response_content)
                    if deconstructed_responses:
                        for deconstructed_response in deconstructed_responses:
                            if deconstructed_response:
                                for response_prop, response_val in deconstructed_response.items():
                                    if response_prop in successful_responses[operation_id] and response_val not in successful_responses[operation_id][response_prop]:
                                        successful_responses[operation_id][response_prop].append(response_val)

            if response is not None: self.responses[response.status_code] += 1

    def output_successes(self, successful_parameters, successful_bodies, successful_responses):

        compiled_successes = {
            "PARAMETERS": successful_parameters,
            "BODIES": successful_bodies,
            "RESPONSES": successful_responses
        }

        output_dir = os.path.join(os.path.dirname(__file__), "data/successful_responses")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(f"{output_dir}/{self.operation_graph.spec_name}.json", "w") as f:
            json.dump(compiled_successes, f, indent=2)

    def run(self):

        successful_parameters = {}
        successful_bodies = {}
        successful_responses = {}
        self._init_parameter_tracking(successful_parameters)
        self._init_body_tracking(successful_bodies)
        self._init_response_tracking(successful_responses)

        self.execute_operations(successful_parameters, successful_bodies, successful_responses)
        self.output_successes(successful_parameters, successful_bodies, successful_responses)

        #self.print_q_tables()
        print("COLLECTED RESPONSES: ", self.responses)
