"""
Safe Mathematical Calculator module for DesktopAssistant.
Uses Python's AST (Abstract Syntax Tree) module for evaluation.
Never uses unrestricted eval().
Supports standard arithmetic and natural spoken math expressions.
"""

import ast
import re
import logging
from typing import Tuple, Union, Optional

logger = logging.getLogger("DesktopAssistant.Calculator")

# Word-to-number mapping for spoken digits/words
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000
}


def words_to_number(phrase: str) -> str:
    """
    Converts simple word-based spoken numbers into numeric strings.
    Example: "twenty five" -> "25", "one hundred" -> "100".
    """
    words = phrase.lower().split()
    result = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in NUMBER_WORDS:
            val = NUMBER_WORDS[w]
            # Look ahead for composite numbers like "twenty five" or "one hundred"
            if i + 1 < len(words) and words[i + 1] in NUMBER_WORDS:
                next_val = NUMBER_WORDS[words[i + 1]]
                if val in (20, 30, 40, 50, 60, 70, 80, 90) and next_val < 10:
                    result.append(str(val + next_val))
                    i += 2
                    continue
                elif val < 10 and next_val == 100:
                    result.append(str(val * 100))
                    i += 2
                    continue
            result.append(str(val))
        else:
            result.append(w)
        i += 1
    return " ".join(result)


def normalize_math_expression(text: str) -> str:
    """
    Normalizes spoken mathematical phrases into valid mathematical symbols.
    Handles 'percent of', 'times', 'multiplied by', 'divided by', 'plus', 'minus', etc.
    """
    expr = text.lower().strip()
    
    # Strip conversational prefixes
    prefixes = [
        "what is", "calculate", "compute", "tell me", "how much is",
        "what does", "evaluate", "solve"
    ]
    for p in prefixes:
        if expr.startswith(p):
            expr = expr[len(p):].strip()

    # Convert spoken word numbers to digits
    expr = words_to_number(expr)

    # Convert percentage patterns: "X percent of Y" -> "(X / 100) * Y"
    percent_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(\d+(?:\.\d+)?)")
    match = percent_pattern.search(expr)
    if match:
        pct, total = match.group(1), match.group(2)
        expr = percent_pattern.sub(f"({pct} / 100) * {total}", expr)

    # Normalize mathematical word operators
    replacements = [
        (r"\bmultiplied by\b", "*"),
        (r"\btimes\b", "*"),
        (r"\bdivided by\b", "/"),
        (r"\bover\b", "/"),
        (r"\badded to\b", "+"),
        (r"\bplus\b", "+"),
        (r"\bsubtracted from\b", "-"),
        (r"\bminus\b", "-"),
        (r"\bto the power of\b", "**"),
        (r"\bsquared\b", "** 2"),
        (r"\bcubed\b", "** 3"),
        (r"\bx\b", "*"),  # spoken letter x as multiplication
    ]

    for pattern, repl in replacements:
        expr = re.sub(pattern, repl, expr)

    # Remove unexpected characters (keep digits, operators, parens, decimal points, spaces)
    expr = re.sub(r"[^\d\+\-\*\/\%\(\)\.\^\s]", "", expr)
    expr = expr.replace("^", "**")
    return expr.strip()


class SafeEvaluator(ast.NodeVisitor):
    """
    AST Visitor that evaluates basic arithmetic expressions strictly.
    Rejects any unapproved AST nodes (functions, attributes, statements, etc.).
    """

    ALLOWED_OPERATORS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b,
        ast.UAdd: lambda a: +a,
        ast.USub: lambda a: -a,
    }

    def visit(self, node):
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        elif isinstance(node, ast.Num):  # Python < 3.8 compatibility
            return node.n
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
            left = self.visit(node.left)
            right = self.visit(node.right)
            if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
                raise ZeroDivisionError("Division by zero")
            return self.ALLOWED_OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            operand = self.visit(node.operand)
            return self.ALLOWED_OPERATORS[op_type](operand)
        else:
            raise ValueError(f"Disallowed expression element: {type(node).__name__}")


def calculate(expression_str: str) -> Tuple[bool, str, Union[int, float, None]]:
    """
    Safely parses and evaluates a math expression string.
    Returns: (success: bool, spoken_response: str, raw_result: number or None)
    """
    normalized = normalize_math_expression(expression_str)
    if not normalized:
        return False, "I could not find a valid math expression to calculate.", None

    try:
        # Parse into AST mode='eval'
        parsed_ast = ast.parse(normalized, mode="eval")
        evaluator = SafeEvaluator()
        result = evaluator.visit(parsed_ast)
        
        # Clean up result representation (e.g. 400 instead of 400.0 if integer)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        elif isinstance(result, float):
            result = round(result, 4)

        spoken_expr = expression_str.strip()
        # Remove conversational leading words from spoken output
        for p in ["what is", "calculate", "compute", "tell me", "how much is"]:
            if spoken_expr.lower().startswith(p):
                spoken_expr = spoken_expr[len(p):].strip()

        response = f"{spoken_expr} equals {result}."
        logger.info(f"Calculator success: '{expression_str}' -> '{normalized}' = {result}")
        return True, response, result

    except ZeroDivisionError:
        logger.warning(f"Calculator zero division error in '{expression_str}'")
        return False, "Division by zero is not allowed.", None
    except Exception as e:
        logger.warning(f"Calculator parsing error for '{expression_str}': {e}")
        return False, "Sorry, I could not calculate that math expression.", None
