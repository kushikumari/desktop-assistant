"""
Local Knowledge Base module for DesktopAssistant.
Provides concise, deterministic local answers for key technical terms.
Does not use cloud APIs or LLMs.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger("DesktopAssistant.Knowledge")

# Concise local knowledge dictionary
KNOWLEDGE_BASE = {
    "ram": (
        "RAM, or Random Access Memory, is high-speed temporary computer memory used "
        "to store data actively needed by running applications."
    ),
    "cpu": (
        "The CPU, or Central Processing Unit, is the primary processor of your computer, "
        "executing system instructions and managing computing tasks."
    ),
    "gpu": (
        "The GPU, or Graphics Processing Unit, is specialized hardware optimized for "
        "rendering graphics and running parallel computational tasks like machine learning."
    ),
    "python": (
        "Python is a popular high-level programming language known for its readability, "
        "versatility, and rich ecosystem in web development, data science, and AI."
    ),
    "generative ai": (
        "Generative AI refers to artificial intelligence models capable of creating new text, "
        "images, code, or audio based on patterns learned from training data."
    ),
    "agentic ai": (
        "Agentic AI describes autonomous systems designed to independently set goals, plan, "
        "use tools, and execute complex workflows with minimal human intervention."
    ),
    "ai": (
        "Artificial Intelligence, or AI, refers to computer systems engineered to simulate "
        "human cognitive functions like reasoning, learning, and problem solving."
    ),
    "operating system": (
        "An Operating System is the core software that controls system hardware, manages files, "
        "and provides standard services for application programs."
    ),
    "windows": (
        "Windows is a personal computer operating system developed by Microsoft that features "
        "a graphical user interface and desktop environment."
    ),
    "browser": (
        "A Web Browser is a software application used to view websites and navigate resources "
        "on the World Wide Web."
    ),
}

# Fallback response for unhandled topics
UNKNOWN_RESPONSE = "I don't know that yet."


def query_knowledge(text: str) -> Tuple[bool, str]:
    """
    Queries local knowledge base with the user's input text.
    
    Returns:
        (found: bool, answer_string: str)
    """
    if not text:
        return False, UNKNOWN_RESPONSE

    # Normalize text
    query = text.lower().strip()
    
    # Strip question filler phrases
    fillers = [
        r"^what\s+is\s+a\b", r"^what\s+is\s+an\b", r"^what\s+is\b",
        r"^what\s+are\b", r"^tell\s+me\s+about\b", r"^explain\b",
        r"^define\b", r"^who\s+is\b", r"^what\s+does\b"
    ]
    for filler in fillers:
        query = re.sub(filler, "", query).strip()

    # Strip trailing punctuation
    query = query.rstrip("?.!")

    logger.debug(f"Normalized knowledge query: '{query}'")

    # Match exact or multi-word terms first (e.g. "generative ai" before "ai")
    sorted_topics = sorted(KNOWLEDGE_BASE.keys(), key=lambda k: len(k), reverse=True)

    for topic in sorted_topics:
        # Check if topic matches normalized query or appears as a distinct word/phrase
        pattern = r"\b" + re.escape(topic) + r"\b"
        if query == topic or re.search(pattern, query):
            logger.info(f"Knowledge match found for topic: '{topic}'")
            return True, KNOWLEDGE_BASE[topic]

    logger.info(f"No knowledge topic matched for: '{text}'")
    return False, UNKNOWN_RESPONSE
