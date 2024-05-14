import json
from typing import Dict

REQUEST_BODY_GEN_PROMPT = """
Given a summary of an operation its request body schema, generate a valid context-aware request body for the operation. Return the answer as a JSON object with the following structure:
{
    "request_body": [correct request body]
}
In the case where the request body is an object, use an object with keys to represent the object field names and values to represent their respective field values for the request body value. Attempt to generate values for all required fields for object request bodies. Attempt to generate as much as possible.
In the case where the request body is an array, use a list as the request_body value.
Do not solely rely on the given constraint values, and ensure you read the associated descriptions for maximum accuracy."""

PARAMETERS_GEN_PROMPT = """
Given a summary of an operation and its parameters schema, generate valid context-aware values for the parameters of the operation. Attempt to generate values for all required parameters. Return the answer as a JSON object with the following structure:
{
    "parameters": {
        "[parameter1]": [value1],
        "[parameter2]": [value2],
        ...
    }
}
In the case where a given parameter is an object, use an object with keys to represent the object field names and values to represent their respective field values as the parameter value. 
In the case where a given parameter is an array, use a list as the parameter value.
Do not solely rely on the given constraint values, and ensure you read the associated descriptions for maximum accuracy."""

#FEWSHOT_REQUEST_BODY_GEN_PROMPT = """
#SUMMARY:
#SCHEMA: {'properties': {'text': {'type': 'string', 'description': "The text to be checked. This or 'data' is required."}, 'data': {'type': 'string', 'description': 'The text to be checked, given as a JSON document that specifies what\'s text and what\'s markup. This or \'text\' is required. Markup will be ignored when looking for errors. Example text: <pre>A &lt;b>test&lt;/b></pre>JSON for the example text: <pre>{"annotation":[\n {"text": "A "},\n {"markup": "&lt;b>"},\n {"text": "test"},\n {"markup": "&lt;/b>"}\n]}</pre> <p>If you have markup that should be interpreted as whitespace, like <tt>&lt;p&gt;</tt> in HTML, you can have it interpreted like this: <pre>{"markup": "&lt;p&gt;", "interpretAs": "\\n\\n"}</pre><p>The \'data\' feature is not limited to HTML or XML, it can be used for any kind of markup.'}, 'language': {'type': 'string', 'description': 'A language code like `en-US`, `de-DE`, `fr`, or `auto` to guess the language automatically (see `preferredVariants` below). For languages with variants (English, German, Portuguese) spell checking will only be activated when you specify the variant, e.g. `en-GB` instead of just `en`.'}, 'altLanguages': {'type': 'string', 'description': 'EXPERIMENTAL: Comma-separated list of language codes to check if a word is not similar to one of the main language (parameter `language`). Unknown words that are similar to a word from the main language will still be considered errors but with type `Hint`. For languages with variants (English, German, Portuguese) you need to specify the variant, e.g. `en-GB` instead of just `en`.'}, 'motherTongue': {'type': 'string', 'description': "A language code of the user's native language, enabling false friends checks for some language pairs."}, 'preferredVariants': {'type': 'string', 'description': 'Comma-separated list of preferred language variants. The language detector used with `language=auto` can detect e.g. English, but it cannot decide whether British English or American English is used. Thus this parameter can be used to specify the preferred variants like `en-GB` and `de-AT`. Only available with `language=auto`.'}, 'enabledRules': {'type': 'string', 'description': 'IDs of rules to be enabled, comma-separated'}, 'disabledRules': {'type': 'string', 'description': 'IDs of rules to be disabled, comma-separated'}, 'enabledCategories': {'type': 'string', 'description': 'IDs of categories to be enabled, comma-separated'}, 'disabledCategories': {'type': 'string', 'description': 'IDs of categories to be disabled, comma-separated'}, 'enabledOnly': {'type': 'boolean', 'description': 'If true, only the rules and categories whose IDs are specified with `enabledRules` or `enabledCategories` are enabled.', 'default': False}}, 'required': ['language']}
#REQUEST_BODY:
#"""

#PARAMETER_REQUIREMENTS_PROMPT = """
#Read each 'description' field for each parameter in the schema to determine restrictions and if the parameter is mutually exclusive with another parameter. Look for key words like 'or' in the description to determine if a parameter is mutually exclusive with another parameter.
#You must generate values for the following parameters unless the description states that the parameter is mutually exclusive with another parameter:
#"""

PARAMETER_REQUIREMENTS_PROMPT = """
Attempt to generate values for the following parameters (attempt the most possible). It is extremely important to ensure the values are compatible with eachother:
"""

RETRY_PARAMETER_REQUIREMENTS_PROMPT = """
Attempt to generate values for the following parameters, unless otherwise specified in the failed response. Ensure the values are compatible with eachother:
"""

FAILED_PARAMETER_MATCHINGS_PROMPT = """
You generated the following values for the parameters, but the request was not successful. Here are the values you generated for the parameters:
"""

FAILED_PARAMETER_RESPONSE_PROMPT = """
Here is the response indicating the reason for the operation failure. Attempt to generate new values for the parameters based on the response. You can exclude certain parameters if indicated by the response:
"""

FEWSHOT_REQUEST_BODY_GEN_PROMPT = """"""

FEWSHOT_PARAMETER_GEN_PROMPT = """"""

def template_gen_prompt(summary: str, schema: Dict) -> str:
    try:
        schema = json.dumps(schema, indent=2)
    except:
        schema = str(schema)
    return f"SUMMARY: {summary}\nSCHEMA: {schema}\n"