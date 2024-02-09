import random
import string
from dataclasses import dataclass
from typing import List

import requests
import urllib
import json
from specification_parser import SpecificationParser, ItemProperties, ParameterProperties


@dataclass
class RequestData:
    endpoint_path: str
    http_method: str
    parameters: dict
    request_body: dict

@dataclass
class StatusCode:
    status_code: int
    count: int
    requests: list[RequestData]

class RequestsGenerator:
    def __init__(self, file_path: str, api_url: str):
        self.file_path = file_path
        self.api_url = api_url
        self.successful_query_data = [] # list that will store successfuly query_parameters
        self.status_codes = {} # dictionary to track status code occurrences

    def process_response(self, response, endpoint_path, http_method, query_parameters, request_body=None):
        # Increment the count for the received status code
        request_data = RequestData(
            endpoint_path=endpoint_path,
            http_method=http_method,
            parameters=query_parameters,
            request_body=request_body
        )

        if response.status_code not in self.status_codes:
            self.status_codes[response.status_code] = StatusCode(
                status_code=response.status_code,
                count=0,
                requests=[]
            )
        else:
            self.status_codes[response.status_code].count += 1
            self.status_codes[response.status_code].requests.append(request_data)

        if response.status_code // 100 == 2:
            self.successful_query_data.append(request_data)

    def send_request(self, endpoint_path, http_method, query_parameters, request_body=None):
        """
        Send the request to the API.
        """
        try:
            method = getattr(requests, http_method)
            if http_method in {"put", "post"}:
                response = method(self.api_url + endpoint_path, params=query_parameters, json=request_body)
            else:
                response = method(self.api_url + endpoint_path, params=query_parameters)
        except requests.exceptions.RequestException:
            print("Request failed")
            return None
        return response

    def randomize_integer(self):
        return random.randint(-2**32, 2**32)

    def randomize_float(self):
        return random.uniform(-2**32, 2**32)

    def randomize_boolean(self):
        return random.choice([True, False])

    def randomize_string(self):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=random.randint(1, 9999)))

    def randomize_array(self):
        return [random.randint(-9999, 9999) for _ in range(random.randint(1, 9999))]

    def randomize_object(self):
        return {random.choice(string.ascii_letters): random.randint(-9999, 9999) for _ in range(random.randint(1, 9999))}

    def randomize_null(self):
        return None

    def randomize_parameter_value(self):
        """
        Randomly generate values of any type
        """
        generators = [self.randomize_integer,
                      self.randomize_float,
                      self.randomize_boolean,
                      self.randomize_string,
                      self.randomize_array,
                      self.randomize_object,
                      self.randomize_null]
        return random.choice(generators)()

    def randomize_values(self, parameters, request_body) -> (dict[str: any], dict):
        # create randomize object here and return after Object.randomize_parameters() and Object.randomize_request_body() is called
        # do randomize parameter selection, then randomize the values for both parameters and request_body
        pass

    def randomize_parameters(self, parameter_dict) -> dict[str, ParameterProperties]:
        """
        Randomly select parameters from the dictionary.
        """
        random_selection = {}
        for parameter_name, parameter_properties in parameter_dict.items():
            if parameter_properties.in_value == "path":
                random_selection[parameter_name] = parameter_properties
            elif random.choice([True, False]):
                random_selection[parameter_name] = parameter_properties
        return random_selection

    def process_operation(self, operation_properties):
        """
        Process the operation properties to generate the request.
        """
        endpoint_path = operation_properties.endpoint_path
        http_method = operation_properties.http_method

        request_body = None
        content_type = None
        if operation_properties.request_body:
            for content_type_value, request_body_properties in operation_properties.request_body_properties.items():
                content_type = content_type_value
                request_body = request_body_properties

        query_parameters, request_body = self.randomize_values(operation_properties.parameters, request_body)

        for parameter_name, parameter_properties in query_parameters.items():
            if parameter_properties.in_value == "path":
                endpoint_path = endpoint_path.replace("{" + parameter_name + "}", str(self.randomize_parameter_value()))

        response = self.send_request(endpoint_path, http_method, query_parameters, request_body)

        if response is not None:
            #processing the response if request was successful
            self.process_response(response, endpoint_path, http_method, query_parameters, request_body)

    def convert_properties(self, object: ItemProperties):
        if object.type == "array":
            num_objects = random.randint(0, 5)
            obj_arr = []
            for _ in range(num_objects):
                obj_arr.append(self.convert_properties(object.items))
            return obj_arr
        elif object.type == "object":
            object_structure = {}
            for key, value in object.properties.items():
                object_structure[key] = self.convert_properties(value)
            return object_structure
        else:
            return self.randomize_parameter_value()

    def convert_request_body(self, parsed_request_body):
        if 'application/json' in parsed_request_body:
            object = parsed_request_body['application/json']
            if isinstance(object, ItemProperties):
                constructed_body = self.convert_properties(object)
                return json.dumps(constructed_body)
            elif isinstance(object, list):
                arr = []
                for obj in object:
                    arr.append(self.convert_properties(obj))
                return json.dumps(arr)
            else:
                raise SyntaxError("Request Body Schema Parsing Error")
        elif 'application/x-www-form-urlencoded' in parsed_request_body:
            object = parsed_request_body['application/x-www-form-urlencoded']
            if isinstance(object, ItemProperties):
                constructed_body = self.convert_properties(object)
                return urllib.urlencode(constructed_body)
            elif isinstance(object, list):
                arr = []
                for obj in object:
                    arr.append(self.convert_properties(obj))
                return urllib.urlencode(arr)
            else:
                raise SyntaxError("Request Body Schema Parsing Error")
        else:
          keys = list(parsed_request_body.keys())
          if len(keys) == 1:
            raise ValueError("Unsupported MIME type: " + keys[0] + " in Request Body Specification")
          else:
              raise SyntaxError("Formatting Error in Specification")
    def requests_generate(self):
        """
        Generate the randomized requests based on the specification file.
        """
        print("Generating Request...")
        print()
        specification_parser = SpecificationParser(self.file_path)
        operations = specification_parser.parse_specification()
        for operation_id, operation_properties in operations.items():
            self.process_operation(operation_properties)
        print()
        print("Generated Request!")

#testing code
if __name__ == "__main__":
    request_generator = RequestsGenerator(file_path="../specs/original/oas/genome-nexus.yaml", api_url="http://localhost:50110")
    request_generator.requests_generate()
    #generate histogram using self.status_code_counts
    print(request_generator.status_code_counts)
    #for i in range(10):
    #    print(request_generator.randomize_parameter_value())