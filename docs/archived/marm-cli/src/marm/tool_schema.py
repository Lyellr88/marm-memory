"""JSON Schema generation from Pydantic models for LLM tool calling"""
from typing import Dict, Any, Type, get_origin, get_args
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class SchemaGenerator:
    """Generate JSON Schema from Pydantic models for LLM function calling"""

    @staticmethod
    def from_pydantic(model: Type[BaseModel]) -> Dict[str, Any]:
        """
        Generate JSON Schema from Pydantic model

        Args:
            model: Pydantic model class

        Returns:
            JSON Schema dict compatible with LLM function calling APIs
        """
        # Pydantic v2 has built-in JSON schema generation
        schema = model.model_json_schema()

        # Extract properties and required fields
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Clean up schema for LLM (remove Pydantic-specific fields)
        cleaned_properties = {}
        for field_name, field_schema in properties.items():
            cleaned_properties[field_name] = SchemaGenerator._clean_field_schema(field_schema)

        return {
            "type": "object",
            "properties": cleaned_properties,
            "required": required
        }

    @staticmethod
    def _clean_field_schema(field_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean field schema for LLM consumption

        Remove Pydantic-specific fields and normalize types
        """
        cleaned = {}

        # Core fields
        if "type" in field_schema:
            cleaned["type"] = field_schema["type"]

        if "description" in field_schema:
            cleaned["description"] = field_schema["description"]
        elif "title" in field_schema:
            # Use title as description if description not present
            cleaned["description"] = field_schema["title"]

        # Handle enum
        if "enum" in field_schema:
            cleaned["enum"] = field_schema["enum"]

        # Handle array items
        if "items" in field_schema:
            cleaned["items"] = SchemaGenerator._clean_field_schema(field_schema["items"])

        # Handle default values
        if "default" in field_schema:
            cleaned["default"] = field_schema["default"]

        # Numeric constraints
        for constraint in ["minimum", "maximum", "minLength", "maxLength"]:
            if constraint in field_schema:
                cleaned[constraint] = field_schema[constraint]

        return cleaned

    @staticmethod
    def validate_params(schema: Dict[str, Any], params: Dict[str, Any]) -> tuple[bool, str]:
        """
        Basic validation of parameters against JSON Schema

        Args:
            schema: JSON Schema dict
            params: Parameters to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check required fields
        for field in required:
            if field not in params:
                return False, f"Missing required parameter: {field}"

        # Check types (basic validation)
        for field, value in params.items():
            if field not in properties:
                logger.warning(f"Unexpected parameter: {field}")
                continue

            field_schema = properties[field]
            expected_type = field_schema.get("type")

            if not SchemaGenerator._check_type(value, expected_type):
                return False, f"Invalid type for {field}: expected {expected_type}, got {type(value).__name__}"

        return True, ""

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON Schema type"""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict
        }

        if expected_type not in type_map:
            return True  # Unknown type, skip validation

        expected_python_type = type_map[expected_type]
        return isinstance(value, expected_python_type)


def generate_function_declaration(
    name: str,
    description: str,
    parameters_schema: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate function declaration for LLM function calling

    Args:
        name: Tool name
        description: Tool description
        parameters_schema: JSON Schema for parameters

    Returns:
        Function declaration dict for LLM API
    """
    return {
        "name": name,
        "description": description,
        "parameters": parameters_schema
    }
