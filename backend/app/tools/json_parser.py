# ============================================================
# VendorScout Pro - Robust JSON Parser
# ============================================================
# Multi-strategy JSON parser that handles common LLM output
# formatting issues. LLMs frequently output malformed JSON:
# - Wrapped in markdown code fences (```json ... ```)
# - Trailing commas in arrays/objects
# - Single quotes instead of double quotes
# - Unicode escapes and special characters
# - Embedded in natural language text
#
# Inspired by agentic-web patterns (openbox-deals, tinyskills).
# The cookbook demonstrates that every LLM response needs defensive
# parsing — production systems WILL encounter all these issues.
# ============================================================

import json
import logging
import re
from typing import Optional, Union

logger = logging.getLogger(__name__)


def parse_json_robust(
    text: str,
    fallback: Optional[dict] = None
) -> Optional[Union[dict, list]]:
    """
    Parse JSON from LLM output using multiple strategies.
    
    Tries strategies in order of strictness:
    1. Direct json.loads() — fastest, handles well-formed JSON
    2. Strip markdown code fences — handles ```json ... ```
    3. Fix trailing commas — common LLM mistake
    4. Single quotes → double quotes — Python-style JSON
    5. Regex extraction — find JSON object/array in arbitrary text
    6. Return fallback if all strategies fail
    
    Args:
        text: Raw LLM output (may contain JSON + other text)
        fallback: Return value if ALL parsing strategies fail
        
    Returns:
        Parsed JSON (dict or list), or fallback value
        
    WHY multi-strategy:
        LLMs are non-deterministic. Even with "Return only JSON" in the
        prompt, they may wrap output in markdown fences, add commentary,
        use trailing commas, etc. Each strategy handles a specific real-world
        failure mode we've encountered in production.
    """
    if not text or not text.strip():
        return fallback
    
    text = text.strip()
    
    # Strategy 1: Direct parse — fastest path for well-formed JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Strip markdown code fences
    # LLMs often wrap JSON in ```json\n...\n``` or ```\n...\n```
    cleaned = _strip_markdown_fences(text)
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    
    # Strategy 3: Fix trailing commas
    # Example: {"items": ["a", "b",]} → {"items": ["a", "b"]}
    no_trailing = _fix_trailing_commas(cleaned)
    if no_trailing != cleaned:
        try:
            return json.loads(no_trailing)
        except json.JSONDecodeError:
            pass
    
    # Strategy 4: Single quotes → double quotes (Python-style dicts)
    # Only attempt if text looks like it uses single quotes for strings
    if "'" in cleaned and '"' not in cleaned[:50]:
        double_quoted = _single_to_double_quotes(cleaned)
        try:
            return json.loads(double_quoted)
        except json.JSONDecodeError:
            pass
    
    # Strategy 5: Combined fixes — trailing commas + quote conversion
    combined = _fix_trailing_commas(_single_to_double_quotes(cleaned))
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        pass
    
    # Strategy 6: Regex extraction — find first JSON object or array in text
    # This handles cases where LLM puts commentary before/after JSON
    extracted = _extract_json_regex(text)
    if extracted is not None:
        return extracted
    
    logger.warning(f"All JSON parse strategies failed. Text preview: {text[:200]}")
    return fallback


def _strip_markdown_fences(text: str) -> str:
    """
    Remove markdown code fences wrapping JSON.
    
    Handles formats:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - ```JSON\n{...}\n```
    """
    # Pattern: ```json or ``` at start, ``` at end
    pattern = r'^```(?:json|JSON)?\s*\n?(.*?)\n?\s*```$'
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Handle case where only opening or closing fence exists
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line if it's ```)
        start = 1
        end = len(lines)
        if lines[-1].strip() == "```":
            end = -1
        return "\n".join(lines[start:end]).strip()
    
    return text


def _fix_trailing_commas(text: str) -> str:
    """
    Remove trailing commas before closing braces/brackets.
    
    Common LLM mistake:
    - {"items": ["a", "b",]} → {"items": ["a", "b"]}
    - {"key": "val",} → {"key": "val"}
    
    Uses regex to safely handle nested structures.
    """
    # Remove trailing commas before } or ]
    # Pattern: comma followed by optional whitespace/newlines, then } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    return fixed


def _single_to_double_quotes(text: str) -> str:
    """
    Convert Python-style single-quoted strings to JSON double quotes.
    
    Careful not to convert apostrophes inside words (e.g., "don't").
    Only converts quotes that look like string delimiters.
    
    WARNING: This is a heuristic and may produce incorrect results
    for complex nested quote patterns. Use as last resort.
    """
    # Simple approach: replace single quotes that are likely string delimiters
    # (preceded/followed by : , [ ] { } or start/end of line)
    result = re.sub(
        r"(?<=[\[{:,\s])'|'(?=[\]}:,\s])",
        '"',
        text
    )
    return result


def _extract_json_regex(text: str) -> Optional[Union[dict, list]]:
    """
    Extract JSON object or array from arbitrary text using regex.
    
    Finds the first balanced { ... } or [ ... ] structure.
    Handles nested braces/brackets by counting depth.
    
    This is the "nuclear option" — used when all simpler parsing fails.
    Works well when LLM outputs commentary before/after JSON.
    """
    # Try finding a JSON object first, then array
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        
        # Count brace/bracket depth to find matching close
        depth = 0
        in_string = False
        escape_next = False
        
        for i in range(start_idx, len(text)):
            char = text[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if in_string:
                continue
            
            if char == start_char:
                depth += 1
            elif char == end_char:
                depth -= 1
                if depth == 0:
                    # Found complete JSON structure
                    json_str = text[start_idx:i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try with trailing comma fix
                        try:
                            return json.loads(_fix_trailing_commas(json_str))
                        except json.JSONDecodeError:
                            break  # Try next start_char type
    
    return None


def extract_field(data: Union[dict, list, str, None], *keys: str) -> Optional[str]:
    """
    Safely extract a text field from parsed data, trying multiple key names.
    
    Useful when LLM output uses inconsistent field names:
    - "content" vs "text" vs "body" vs "extracted_content"
    
    Inspired by tinyskills cookbook parseScrapedContent() pattern.
    
    Args:
        data: Parsed JSON data (dict, list, or string)
        *keys: Key names to try in order
        
    Returns:
        First matching string value, or None
    """
    if data is None:
        return None
    
    if isinstance(data, str):
        return data
    
    if isinstance(data, list):
        # For arrays, try to stringify meaningfully
        parts = []
        for item in data:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(json.dumps(item))
        return "\n".join(parts) if parts else None
    
    if isinstance(data, dict):
        for key in keys:
            val = data.get(key)
            if val is not None:
                if isinstance(val, str):
                    return val
                return json.dumps(val)
    
    return None
