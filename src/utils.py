import base64
import hashlib
import json
from typing import Iterable, Dict, List, Any, Optional, Tuple, Set
import itertools

from openai import OpenAI
from dotenv import load_dotenv
import os

from src.graph.specification_parser import ParameterProperties, SchemaProperties
from src.prompts.generator_prompts import FIX_JSON_OBJ
from src.prompts.system_prompts import DEFAULT_SYSTEM_MESSAGE, FIX_JSON_SYSTEM_MESSAGE

load_dotenv()

def remove_nulls(item):
    if hasattr(item, 'to_dict'):
        return item.to_dict()
    elif isinstance(item, dict):
        return {k: remove_nulls(v) for k, v in item.items() if v is not None and remove_nulls(v) is not None}
    elif isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
        return [remove_nulls(i) for i in item if remove_nulls(i) is not None]
    else:
        return item

def get_param_combinations(operation_parameters: Dict[str, ParameterProperties]) -> List[Tuple[str]]:
    return get_combinations(get_params(operation_parameters))

def get_body_combinations(operation_body: Dict[str, SchemaProperties]) -> Dict[str, List[Tuple[str]]]:
    return {k: get_combinations(v) for k, v in get_request_body_params(operation_body).items()}

def get_body_object_combinations(body_schema: SchemaProperties) -> List[Tuple[str]]:
    return get_combinations(process_body_params(body_schema))

def get_combinations(arr) -> List[Tuple]:
    combinations = []
    for i in range(1, len(arr)+1):
        combinations.extend(list(itertools.combinations(arr, i)))
    return combinations

def get_params(operation_parameters: Dict[str, ParameterProperties]) -> List[str]:
    return list(operation_parameters.keys()) if operation_parameters is not None else []

def get_required_params(operation_parameters: Dict[str, ParameterProperties]) -> Set:
    required_parameters = set()
    for parameter, parameter_properties in operation_parameters.items():
        if parameter_properties.required:
            required_parameters.add(parameter)
    return required_parameters

def get_required_body_params(operation_body: SchemaProperties) -> Set:
    if operation_body is None:
        return None
    required_body = set()

    if operation_body.properties and operation_body.type == "object":
        for key, value in operation_body.properties.items():
            # Do check for "container" objects that are just an array of values
            if len(operation_body.properties) == 1 and value.type == "array":
                required_body = get_required_body_params(value.items)

            elif value.required:
                required_body.add(key)

    elif operation_body.items and operation_body.type == "array":
        required_body = get_required_body_params(operation_body.items)

    else:
        return None
    return required_body

def encode_dict_as_key(dictionary: Dict) -> str:
    json_str = json.dumps(dictionary, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()

def process_body_params(body: SchemaProperties) -> List[str]:
    if body is None:
        return []
    elif body.properties and body.type == "object":
        body_params = []
        for key, value in body.properties.items():
            # Do check for "container" objects that are just an array of values
            if len(body.properties) == 1 and value.type == "array":
                body_params = process_body_params(value.items)

            else:
                body_params.append(key)

        return body_params
    elif body.items and body.type == "array":
        return process_body_params(body.items)

    return []

def get_request_body_params(operation_body: Dict[str, SchemaProperties]) -> Dict[str, List[str]]:
    return {k: process_body_params(v) for k, v in operation_body.items()} if operation_body is not None else {}

def get_nested_obj_mappings(thing: Any) -> Optional[Dict[str, Any]]:
    """
    Determine the mappings of a given item that contains some nested objects
    :param thing: The thing to get the mappings for
    :return:
    """
    # Note: Checked and no need to do len(1) check for object (not used for any obj param matching)
    if not thing:
        return None
    mappings = {}
    if type(thing) == dict:
        for key, value in thing.items():
            mappings[key] = value
    elif type(thing) == list and len(thing) > 0:
        mappings = get_nested_obj_mappings(thing[0])
    return mappings

def compose_json_fix_prompt(invalid_json_str: str):
    prompt = FIX_JSON_OBJ
    prompt += invalid_json_str
    return prompt

def attempt_fix_json(invalid_json_str: str):
    language_model = OpenAILanguageModel(engine="gpt-4o",temperature=0.3)
    json_prompt = compose_json_fix_prompt(invalid_json_str)
    fixed_json = language_model.query(user_message=json_prompt, system_message=FIX_JSON_SYSTEM_MESSAGE,
                                           json_mode=True)
    try:
        fixed_json = json.loads(fixed_json)
        return fixed_json
    except json.JSONDecodeError:
        print("Attempt to fix JSON string failed.")
        print(f"Original JSON string: {invalid_json_str}")
        print(f"Fixed JSON string: {fixed_json}")
        return {}

# OpenAI available engines = ["gpt-3.5-turbo-0125", "gpt-4o"]

COST_PER_TOKEN = {
    "gpt-3.5-turbo-0125": 0.5*10**-6,
    "gpt-4o": 5*10**-6
}

class OpenAILanguageModel:
    cumulative_cost = 0
    cache = {}

    @staticmethod
    def get_cumulative_cost():
        return OpenAILanguageModel.cumulative_cost

    def __init__(self, engine = "gpt-3.5-turbo-0125", temperature = 0.8, max_tokens = 4000):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if self.api_key is None or self.api_key.strip() == "":
            raise ValueError("OPENAI API key is required for OpenAI language model, found None or empty string.")
        self.client = OpenAI(api_key=self.api_key)
        self.engine = engine
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _generate_cache_key(self, user_message, system_message, json_mode):
        key_data = {
            "user_message": user_message,
            "system_message": system_message,
            "json_mode": json_mode,
            "engine": self.engine,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode('utf-8')).hexdigest()

    def query(self, user_message, system_message = DEFAULT_SYSTEM_MESSAGE, json_mode = False) -> str:
        cache_key = self._generate_cache_key(user_message, system_message, json_mode)
        if cache_key in OpenAILanguageModel.cache:
            return OpenAILanguageModel.cache[cache_key]

        if json_mode:
            response = self.client.chat.completions.create(
                model=self.engine,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type":"json_object"}
            )
        else:
            response = self.client.chat.completions.create(
                model=self.engine,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

        total_tokens = response.usage.total_tokens
        OpenAILanguageModel.cumulative_cost += total_tokens * COST_PER_TOKEN[self.engine]
        result = response.choices[0].message.content.strip()

        OpenAILanguageModel.cache[cache_key] = result
        return result

def _construct_db_dir():
    db_path = os.path.join(os.path.dirname(__file__), "data/")
    if not os.path.exists(db_path):
        os.makedirs(db_path)

def construct_basic_token(token):
    username = token.get("username")
    password = token.get("password")
    token_str = f"{username}:{password}"
    encoded_bytes = base64.b64encode(token_str.encode("utf-8"))
    encoded_str = encoded_bytes.decode("utf-8")
    return f"Basic {encoded_str}"
