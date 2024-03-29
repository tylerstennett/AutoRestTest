from dataclasses import dataclass
from typing import Dict, AnyStr, Set, Any

from .generate_graph import OperationGraph, OperationNode, OperationEdge
from .specification_parser import OperationProperties, ParameterProperties, SchemaProperties
import requests

from .value_generator import NaiveValueGenerator, identify_generator


@dataclass
class RequestData:
    endpoint_path: AnyStr
    http_method: AnyStr
    parameter_values: Dict[AnyStr, Any] # dict of parameter name to value
    request_body: AnyStr
    content_type: AnyStr
    operation_id: AnyStr
    operation_properties: OperationProperties

@dataclass
class RequestResponse:
    request: RequestData
    response: requests.Response
    response_text: str

@dataclass
class StatusCode:
    status_code: int
    count: int
    requests_and_responses: List[RequestResponse]


class NaiveRequestGenerator:
    def __init__(self, operation_graph: OperationGraph, api_url: str):
        self.operation_graph: OperationGraph = operation_graph
        self.api_url = api_url  
        self.status_codes: Dict[int: StatusCode] = {} # dictionary to track status code occurrences
        self.requests_generated = 0  # Initialize the request count
        self.successful_query_data = [] # List to store successful query data

    def generate_parameter_values(self, parameters: Dict[AnyStr, ParameterProperties], request_body: Dict[AnyStr, SchemaProperties]):
        value_generator = NaiveValueGenerator(parameters=parameters, request_body=request_body)
        return value_generator.generate_parameters() if parameters else None, value_generator.generate_request_body() if request_body else None

    def process_response(self, response: requests.Response, request_data: RequestData):
        """
        Process the response from the API.
        """
        if response is None:
            return

        self.requests_generated += 1

        # print(response.text)
        request_and_response = RequestResponse(
            request=request_data,
            response=response,
            response_text=response.text
        )

        if response.status_code not in self.status_codes:
            self.status_codes[response.status_code] = StatusCode(
                status_code=response.status_code,
                count=1,
                requests_and_responses=[request_and_response],
            )
        else:
            self.status_codes[response.status_code].count += 1
            self.status_codes[response.status_code].requests_and_responses.append(request_and_response)

        if response.status_code // 100 == 2:
            self.successful_query_data.append(request_data)


    def send_operation_request(self, request_data: RequestData):
        '''
        Generate naive requests based on the default values and types
        '''
        # endpoint_path: AnyStr = operation_properties.endpoint_path
        # for parameter_name, parameter_properties in operation_properties.parameters.items():
        #     if parameter_properties.in_value == "path":
        #         get_path_value = identify_generator(parameter_properties.schema.type)
        #         endpoint_path.replace("{"+parameter_name+"}", get_path_value)

        # parameters, request_body = self.generate_parameter_values(operation_properties.parameters, operation_properties.request_body)

        '''
        Send the request to the API using the request data.
        '''
        endpoint_path = request_data.endpoint_path
        http_method = request_data.http_method
        parameters = request_data.parameters
        request_body = request_data.request_body
        content_type = request_data.content_type

        try:
            # Choose the appropriate method from the 'requests' library based on the HTTP method
            select_method = getattr(requests, http_method)
            full_url = f"{self.api_url}{endpoint_path}"

            # Prepare and send the request
            if http_method in {"put", "post", "patch"}:
                # For PUT, POST, and PATCH requests, include the request body
                response = select_method(full_url, params=parameters, json=request_body)
            else:
                # For GET and DELETE requests, send only the parameters
                response = select_method(full_url, params=parameters)

            # Handle the response as needed
            print(f"Request to {http_method.upper()} {endpoint_path} completed with status code {response.status_code}")
            return response

        except requests.exceptions.RequestException as err:
            print(f"Request failed due to error: {err}")
            print(f"Endpoint Path: {endpoint_path}")
            print(f"Params: {parameters}")
            return None
        except Exception as err:
            print(f"Request failed due to error: {err}")
            print(f"Endpoint Path: {endpoint_path}")
            print(f"Params: {parameters}")
            return None
        
    def process_operation(self, operation_properties: OperationProperties) -> RequestData:
        '''
        Process the operation properties to prepare the request data.
        '''
        endpoint_path = operation_properties.endpoint_path
        http_method = operation_properties.http_method.lower()

        # Generate values for parameters and request body
        parameters, request_body = self.generate_parameter_values(
            operation_properties.parameters, operation_properties.request_body
        )

        # Replace path parameters in the endpoint path
        for parameter_name, parameter_properties in operation_properties.parameters.items():
            if parameter_properties.in_value == "path":
                path_value = parameters[parameter_name]
                endpoint_path = endpoint_path.replace("{" + parameter_name + "}", str(path_value))

        # Determine the content type
        content_type = "application/json"  

        # Create RequestData object
        return RequestData(
            endpoint_path=endpoint_path,
            http_method=http_method,
            parameters=parameters,
            request_body=request_body,
            content_type=content_type,
            operation_id=operation_properties.operation_id
        )
    
    
    
    def depth_traversal(self, curr_node: OperationNode, visited: Set):
        '''
        Generate low-level requests (with no dependencies and hence high depth) first
        '''
        visited.add(curr_node.operation_id)
        for edge in curr_node.outgoing_edges:
            if edge.destination.operation_id not in visited:
                self.depth_traversal(edge.destination, visited)
        request_data = self.process_operation(curr_node.operation_properties)
        response = self.send_operation_request(request_data)
        if response is not None:
            self.process_response(response, request_data)
            # self.attempt_retry(response, request_data)


    def generate_requests(self):
        '''
        Generate naive requests based on the operation graph
        '''
        visited = set()
        for operation_id, operation_node in self.operation_graph.operation_nodes.items():
            if operation_id not in visited:
                self.depth_traversal(operation_node, visited)


def setup_request_generation():
    api_url = "http://0.0.0.0:9002"  # API URL for genome-nexus
    spec_path = "specs/original/oas/genome-nexus.yaml"  # Specification path

    # Create and populate the operation graph
    operation_graph = OperationGraph(spec_path, spec_name="genome-nexus")
    operation_graph.create_graph()  # Generate the graph

    for operation_id, operation_node in operation_graph.operation_nodes.items():
        print("=====================================")
        print(f"Operation: {operation_id}")
        for edge in operation_node.outgoing_edges:
            print(f"Edge: {edge.source.operation_id} -> {edge.destination.operation_id} with parameters: {edge.similar_parameters}")
        for tentative_edge in operation_node.tentative_edges:
            print(f"Tentative Edge: {tentative_edge.source.operation_id} -> {tentative_edge.destination.operation_id} with parameters: {tentative_edge.similar_parameters}")
        print()
        print()

    # Create the request generator with the populated graph
    request_generator = NaiveRequestGenerator(operation_graph, api_url)
    return request_generator

if __name__ == "__main__":
    generator = setup_request_generation()
    generator.generate_requests()