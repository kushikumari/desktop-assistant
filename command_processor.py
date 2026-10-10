"""
Command Processor module for DesktopAssistant.
Implements deterministic intent recognition and response generation pipeline.
"""

import re
import datetime
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from windows_actions import (
    match_and_execute_action,
    execute_youtube_search,
    execute_open_chatgpt,
    execute_ask_chatgpt,
    execute_play_spotify_song,
    execute_send_whatsapp_message
)
from calculator import calculate
from knowledge import query_knowledge, UNKNOWN_RESPONSE

logger = logging.getLogger("DesktopAssistant.CommandProcessor")


@dataclass
class CommandResult:
    """Represents the outcome of a processed text command."""
    raw_input: str
    normalized_input: str
    intent: str
    response_text: str
    should_exit: bool = False
    action_success: bool = True


def strip_trailing_punctuation(text: str) -> str:
    """Strips trailing punctuation marks (e.g. '.', '?', '!', ',', ';', ':') and extra whitespace."""
    if not text:
        return ""
    cleaned = re.sub(r"[\.\?\!\,\;\:\"]+$", "", text.strip())
    return cleaned.strip()


def normalize_text(text: str) -> str:
    """Normalizes input text by lowercasing, stripping extra whitespace and punctuation."""
    if not text:
        return ""
    clean = strip_trailing_punctuation(text).lower()
    clean = re.sub(r"[^\w\s\+\-\*\/\%\^\.]", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def parse_youtube_search(raw_text: str) -> Tuple[bool, Optional[str]]:
    """Extracts YouTube search query from natural language command, free of trailing punctuation."""
    if not raw_text:
        return False, None
    clean_text = strip_trailing_punctuation(raw_text)
    lower = clean_text.lower().strip()
    if "youtube" not in lower:
        return False, None

    patterns = [
        r"search\s+youtube\s+for\s+(.+)",
        r"search\s+youtube\s+(.+)",
        r"search\s+for\s+(.+)\s+on\s+youtube",
        r"find\s+videos\s+about\s+(.+)\s+on\s+youtube",
        r"find\s+videos\s+on\s+(.+)\s+on\s+youtube",
        r"find\s+(.+)\s+videos\s+on\s+youtube",
        r"find\s+(.+)\s+on\s+youtube",
        r"look\s+up\s+(.+)\s+on\s+youtube",
        r"look\s+up\s+(.+)\s+tutorials\s+on\s+youtube",
        r"youtube\s+search\s+for\s+(.+)",
        r"youtube\s+search\s+(.+)",
        r"open\s+youtube\s+and\s+search\s+for\s+(.+)",
        r"search\s+(.+)\s+on\s+youtube",
    ]

    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            query = strip_trailing_punctuation(m.group(1))
            if query:
                return True, query

    if lower.startswith("search youtube"):
        q = re.sub(r"^search\s+youtube\s+(for\s+)?", "", lower).strip()
        q = strip_trailing_punctuation(q)
        if q:
            return True, q
    if lower.endswith("on youtube"):
        q = re.sub(r"\s+on\s+youtube$", "", lower).strip()
        for prefix in ["search for", "search", "find videos about", "find videos on", "find", "look up"]:
            if q.startswith(prefix):
                q = q[len(prefix):].strip()
        q = strip_trailing_punctuation(q)
        if q:
            return True, q

    return False, None


def _clean_chatgpt_query(query: str) -> str:
    """Cleans extracted ChatGPT query by stripping trailing 'in ChatGPT', trailing punctuation, quotes, and extra whitespace."""
    if not query:
        return ""
    # Strip trailing references to ChatGPT like "in ChatGPT", "on ChatGPT", "using ChatGPT", "via ChatGPT", "with ChatGPT"
    cleaned = re.sub(r"\s+(?:in|on|using|with|via)\s+chat[\s\-]*gpt$", "", query, flags=re.IGNORECASE).strip()
    # Strip leading phrases like "for", "about" if left behind
    cleaned = re.sub(r"^(?:for|about)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = strip_trailing_punctuation(cleaned)
    cleaned = cleaned.strip("'\"`").strip()
    # Normalize multiple internal spaces to a single space
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_ask_chatgpt(raw_text: str) -> Tuple[bool, Optional[str]]:
    """
    Detects intent to search/ask ChatGPT and extracts the topic query.
    
    Supported variations include:
    - "search for merge sort in ChatGPT" -> "merge sort"
    - "search binary search in ChatGPT" -> "binary search"
    - "ask ChatGPT about quick sort" -> "quick sort"
    - "Search for Java exceptions in ChatGPT" -> "Java exceptions"
    - "Search Java exceptions in ChatGPT" -> "Java exceptions"
    - "Ask ChatGPT for the code of binary search" -> "code of binary search"
    - "Search ChatGPT for merge sort code in C" -> "merge sort code in C"
    - "Ask ChatGPT how to reverse a linked list" -> "how to reverse a linked list"
    - "Search in ChatGPT for Java polymorphism examples" -> "Java polymorphism examples"
    - "Ask ChatGPT to explain binary search" -> "explain binary search"
    """
    if not raw_text:
        return False, None

    clean_text = strip_trailing_punctuation(raw_text)
    lower = clean_text.lower().strip()
    norm = re.sub(r"chat[\s\-]*gpt", "chatgpt", lower)
    norm = re.sub(r"\s+", " ", norm)

    if "chatgpt" not in norm:
        return False, None

    # Ignore generic open commands
    generic_open = [
        "open chatgpt", "launch chatgpt", "start chatgpt",
        "open chatgpt in browser", "chatgpt", "open chat gpt",
        "launch chat gpt", "start chat gpt", "open chat-gpt",
        "launch chat-gpt", "start chat-gpt"
    ]
    if norm in generic_open:
        return False, None

    patterns = [
        r"^(?:search|find|look\s+up|ask)(?:\s+for|\s+about)?\s+(.+?)\s+(?:in|on|using|with|via)\s+chatgpt$",
        r"^(?:search|find|look\s+up|ask)\s+(?:in|on|via)\s+chatgpt(?:\s+for|\s+about)?\s+(.+)$",
        r"^open\s+chatgpt\s+(?:and|to)\s+(?:search|ask)(?:\s+for|\s+about)?\s+(.+)$",
        r"^search\s+chatgpt(?:\s+for|\s+about)?\s+(.+)$",
        r"^ask\s+chatgpt\s+for\s+the\s+(.+)$",
        r"^ask\s+chatgpt\s+for\s+(.+)$",
        r"^ask\s+chatgpt\s+to\s+search(?:\s+for|\s+about)?\s+(.+)$",
        r"^ask\s+chatgpt\s+to\s+(.+)$",
        r"^ask\s+chatgpt\s+about\s+(.+)$",
        r"^ask\s+chatgpt\s+(.+)$",
        r"^query\s+chatgpt(?:\s+for|\s+about)?\s+(.+)$",
        r"^chatgpt\s+(?:search|query)(?:\s+for|\s+about)?\s+(.+)$",
        r"^(.+?)\s+(?:in|on)\s+chatgpt$",
    ]

    for pat in patterns:
        m = re.search(pat, norm)
        if m:
            query = _clean_chatgpt_query(m.group(1))
            if query and query.lower() not in ["open", "launch", "start", "app", "browser"]:
                orig_pat = pat.replace("chatgpt", r"chat[\s\-]*gpt")
                m_orig = re.search(orig_pat, clean_text, re.IGNORECASE)
                if m_orig:
                    extracted = _clean_chatgpt_query(m_orig.group(1))
                    if extracted:
                        if clean_text.isupper():
                            return True, extracted.lower()
                        return True, extracted
                return True, query

    return False, None


def parse_open_chatgpt(raw_text: str) -> bool:
    """Detects intent to open ChatGPT in browser."""
    if not raw_text:
        return False
    clean_text = strip_trailing_punctuation(raw_text)
    lower = clean_text.lower().strip()
    norm = re.sub(r"chat[\s\-]*gpt", "chatgpt", lower)
    norm = re.sub(r"\s+", " ", norm)

    is_ask, _ = parse_ask_chatgpt(raw_text)
    if is_ask:
        return False

    chatgpt_phrases = [
        "open chatgpt", "launch chatgpt", "start chatgpt",
        "open chatgpt in browser", "chatgpt"
    ]
    if norm in chatgpt_phrases:
        return True
    if "chatgpt" in norm:
        if any(w in norm for w in ["open", "launch", "start", "browser"]):
            return True
    return False


def parse_play_spotify(raw_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Detects intent to play a specific song on desktop Spotify and extracts song/artist without punctuation."""
    if not raw_text:
        return False, None, None
    clean_text = strip_trailing_punctuation(raw_text)
    lower = clean_text.lower().strip()

    generic_open = [
        "open spotify", "launch spotify", "start spotify", "open spotify app",
        "launch spotify app", "start spotify app"
    ]
    if lower in generic_open:
        return False, None, None

    play_prefixes = ["play ", "put on ", "listen to ", "start playing "]
    has_play_prefix = any(lower.startswith(p) for p in play_prefixes)
    has_spotify_keyword = "on spotify" in lower or "in spotify" in lower

    if not (has_play_prefix or has_spotify_keyword):
        return False, None, None

    cleaned = lower
    for ref in [" on spotify", " in spotify", " spotify"]:
        cleaned = cleaned.replace(ref, "")

    for prefix in play_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    cleaned = strip_trailing_punctuation(cleaned)
    if not cleaned:
        return False, None, None

    if " by " in cleaned:
        parts = cleaned.split(" by ", 1)
        song = strip_trailing_punctuation(parts[0])
        artist = strip_trailing_punctuation(parts[1])
        return True, song, artist
    else:
        song = strip_trailing_punctuation(cleaned)
        return True, song, None


def parse_send_whatsapp_message(raw_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Detects intent to draft a WhatsApp message and extracts recipient and message.
    """
    if not raw_text:
        return False, None, None

    clean_text = strip_trailing_punctuation(raw_text)
    lower = clean_text.lower().strip()

    if "whatsapp" not in lower:
        return False, None, None

    # Ignore generic application open commands for WhatsApp
    generic_open = [
        "open whatsapp", "launch whatsapp", "start whatsapp", "open whatsapp app",
        "launch whatsapp app", "start whatsapp app"
    ]
    if lower in generic_open:
        return False, None, None

    patterns = [
        # "Send hi to Shreyas on WhatsApp" / "Send 'I'll call you later' to Shreyas on WhatsApp"
        r"^send\s+['\"]?(.+?)['\"]?\s+to\s+(.+?)\s+on\s+whatsapp$",
        r"^send\s+['\"]?(.+?)['\"]?\s+to\s+(.+?)\s+in\s+whatsapp$",
        
        # "Message Shreyas on WhatsApp saying I'll be late"
        r"^message\s+(.+?)\s+on\s+whatsapp\s+(?:saying|that|with)\s+['\"]?(.+?)['\"]?$",
        
        # "WhatsApp Shreyas and say I'll reach in 10 minutes"
        r"^whatsapp\s+(.+?)\s+(?:and\s+say|saying|and\s+tell|and\s+send)\s+['\"]?(.+?)['\"]?$",
        
        # "Send a message to Shreyas on WhatsApp saying hi"
        r"^send\s+a\s+message\s+to\s+(.+?)\s+on\s+whatsapp\s+(?:saying|that|with)?\s*['\"]?(.+?)['\"]?$",
    ]

    for pat in patterns:
        m = re.search(pat, clean_text, re.IGNORECASE)
        if m:
            g1 = m.group(1).strip()
            g2 = m.group(2).strip()
            if pat.startswith(r"^message") or pat.startswith(r"^whatsapp") or pat.startswith(r"^send\s+a\s+message\s+to"):
                recipient = g1
                msg = g2
            else:
                msg = g1
                recipient = g2

            msg = msg.strip("'\"")
            recipient = recipient.strip("'\"")
            return True, recipient, msg

    m_fall = re.search(r"^send\s+(.+)\s+to\s+(.+)\s+(?:on|in)\s+whatsapp$", clean_text, re.IGNORECASE)
    if m_fall:
        msg = m_fall.group(1).strip("'\" ")
        recipient = m_fall.group(2).strip("'\" ")
        return True, recipient, msg

    return False, None, None


def get_current_time_response() -> str:
    """Generates natural spoken string for current Windows system time."""
    now = datetime.datetime.now()
    # Format e.g. "4:30 PM"
    time_str = now.strftime("%I:%M %p").lstrip("0")
    return f"The current time is {time_str}."


def get_current_date_response() -> str:
    """Generates natural spoken string for current Windows system date."""
    now = datetime.datetime.now()
    # Format e.g. "Monday, October 5, 2026"
    date_str = now.strftime("%A, %B %d, %Y")
    # Clean leading zeros in day if any
    date_str = date_str.replace(" 0", " ")
    return f"Today's date is {date_str}."


def process_command(raw_text: str) -> CommandResult:
    """
    Main processing pipeline for incoming transcribed voice/text commands.
    
    Pipeline steps:
    1. Input normalization
    2. Exit/Shutdown command check
    3. SEARCH_YOUTUBE intent check
    4. OPEN_CHATGPT intent check
    5. PLAY_SPOTIFY_SONG intent check
    6. Windows application actions check (includes generic "Open Spotify")
    7. Date/Time query check
    8. Math/Calculator evaluation check
    9. Knowledge base lookup check
    10. Fallback unknown command response
    """
    if raw_text == "__NO_WISPR_TEXT__":
        logger.info("Diagnostic received: No new Wispr text received.")
        return CommandResult(
            raw_input=raw_text,
            normalized_input="",
            intent="DIAGNOSTIC",
            response_text="No new Wispr text received.",
            should_exit=False,
            action_success=True
        )

    if not raw_text or not raw_text.strip():
        logger.warning("Received empty or blank command text.")
        return CommandResult(
            raw_input=raw_text,
            normalized_input="",
            intent="EMPTY",
            response_text="I didn't hear any command.",
            should_exit=False,
            action_success=False
        )

    norm_text = normalize_text(raw_text)
    logger.info("=== LIVE COMMAND PROCESSING TRACE START ===")
    logger.info(f"1. RAW TRANSCRIPT RECEIVED: '{raw_text}'")
    logger.info(f"2. NORMALIZED COMMAND: '{norm_text}'")
    logger.info("3. COMMAND PROCESSOR FUNCTION: command_processor.process_command()")

    # 1. Exit / Shutdown intent check
    exit_phrases = ["exit", "quit", "stop", "close assistant", "exit assistant", "quit assistant", "stop assistant"]
    if norm_text in exit_phrases or raw_text.lower().strip() in exit_phrases:
        logger.info("4. DETECTED INTENT: EXIT")
        logger.info("5. EXTRACTED PARAMETERS: None")
        logger.info("6. SELECTED ACTION: shutdown()")
        logger.info("7. ACTION EXECUTION RESULT: Success (Exiting assistant)")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="EXIT",
            response_text="Goodbye! Closing DesktopAssistant.",
            should_exit=True,
            action_success=True
        )

    # 2. SEARCH_YOUTUBE intent check
    is_yt, yt_query = parse_youtube_search(raw_text)
    if is_yt and yt_query:
        logger.info("4. DETECTED INTENT: SEARCH_YOUTUBE")
        logger.info(f"5. EXTRACTED PARAMETERS: query='{yt_query}'")
        logger.info("6. SELECTED ACTION: windows_actions.execute_youtube_search()")
        yt_success, yt_msg = execute_youtube_search(yt_query)
        logger.info(f"7. ACTION EXECUTION RESULT: Success={yt_success}, Message='{yt_msg}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="SEARCH_YOUTUBE",
            response_text=yt_msg,
            should_exit=False,
            action_success=yt_success
        )

    # 3. CHATGPT_SEARCH intent check
    is_ask_gpt, ask_gpt_query = parse_ask_chatgpt(raw_text)
    if is_ask_gpt and ask_gpt_query:
        logger.info("4. DETECTED INTENT: CHATGPT_SEARCH")
        logger.info(f"5. EXTRACTED PARAMETERS: query='{ask_gpt_query}'")
        logger.info("6. SELECTED ACTION: windows_actions.execute_ask_chatgpt()")
        ask_success, ask_msg = execute_ask_chatgpt(ask_gpt_query)
        logger.info(f"7. ACTION EXECUTION RESULT: Success={ask_success}, Message='{ask_msg}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="CHATGPT_SEARCH",
            response_text=ask_msg,
            should_exit=False,
            action_success=ask_success
        )

    # 4. OPEN_CHATGPT intent check
    if parse_open_chatgpt(raw_text):
        logger.info("4. DETECTED INTENT: OPEN_CHATGPT")
        logger.info("5. EXTRACTED PARAMETERS: None")
        logger.info("6. SELECTED ACTION: windows_actions.execute_open_chatgpt()")
        gpt_success, gpt_msg = execute_open_chatgpt()
        logger.info(f"7. ACTION EXECUTION RESULT: Success={gpt_success}, Message='{gpt_msg}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="OPEN_CHATGPT",
            response_text=gpt_msg,
            should_exit=False,
            action_success=gpt_success
        )

    # 4. PLAY_SPOTIFY_SONG intent check
    is_sp, sp_song, sp_artist = parse_play_spotify(raw_text)
    if is_sp and sp_song:
        logger.info("4. DETECTED INTENT: PLAY_SPOTIFY_SONG")
        logger.info(f"5. EXTRACTED PARAMETERS: song='{sp_song}', artist='{sp_artist}'")
        logger.info("6. SELECTED ACTION: windows_actions.execute_play_spotify_song()")
        sp_success, sp_msg = execute_play_spotify_song(sp_song, sp_artist)
        logger.info(f"7. ACTION EXECUTION RESULT: Success={sp_success}, Message='{sp_msg}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="PLAY_SPOTIFY_SONG",
            response_text=sp_msg,
            should_exit=False,
            action_success=sp_success
        )

    # 5. SEND_WHATSAPP_MESSAGE intent check
    is_wa, wa_rec, wa_msg = parse_send_whatsapp_message(raw_text)
    if is_wa and wa_rec and wa_msg:
        logger.info("4. DETECTED INTENT: SEND_WHATSAPP_MESSAGE")
        logger.info(f"5. EXTRACTED PARAMETERS: recipient='{wa_rec}', message='{wa_msg}'")
        logger.info("6. SELECTED ACTION: windows_actions.execute_send_whatsapp_message()")
        wa_success, wa_resp = execute_send_whatsapp_message(wa_rec, wa_msg)
        logger.info(f"7. ACTION EXECUTION RESULT: Success={wa_success}, Message='{wa_resp}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="SEND_WHATSAPP_MESSAGE",
            response_text=wa_resp,
            should_exit=False,
            action_success=wa_success
        )

    # 6. Windows Application launch intent check
    is_action, action_key, action_msg, action_success = match_and_execute_action(raw_text)
    if is_action:
        logger.info(f"4. DETECTED INTENT: WINDOWS_ACTION ({action_key})")
        logger.info(f"5. EXTRACTED PARAMETERS: action_key='{action_key}'")
        logger.info("6. SELECTED ACTION: windows_actions.launch_windows_action()")
        logger.info(f"7. ACTION EXECUTION RESULT: Success={action_success}, Message='{action_msg}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="WINDOWS_ACTION",
            response_text=action_msg,
            should_exit=False,
            action_success=action_success
        )

    # 6. Time / Date intent check
    if any(p in norm_text for p in ["what time is it", "tell me the time", "current time", "what is the time", "time is it"]):
        time_resp = get_current_time_response()
        logger.info("4. DETECTED INTENT: TIME_DATE (Time)")
        logger.info("5. EXTRACTED PARAMETERS: None")
        logger.info("6. SELECTED ACTION: get_current_time_response()")
        logger.info(f"7. ACTION EXECUTION RESULT: Success=True, Response='{time_resp}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="TIME_DATE",
            response_text=time_resp,
            should_exit=False,
            action_success=True
        )

    if any(p in norm_text for p in ["what is todays date", "what is today date", "tell me the date", "what date is it", "current date", "todays date"]):
        date_resp = get_current_date_response()
        logger.info("4. DETECTED INTENT: TIME_DATE (Date)")
        logger.info("5. EXTRACTED PARAMETERS: None")
        logger.info("6. SELECTED ACTION: get_current_date_response()")
        logger.info(f"7. ACTION EXECUTION RESULT: Success=True, Response='{date_resp}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="TIME_DATE",
            response_text=date_resp,
            should_exit=False,
            action_success=True
        )

    # 7. Math / Calculator intent check
    math_keywords = ["plus", "minus", "times", "divided", "multiply", "subtracted", "percent of", "%", "+", "-", "*", "/", "^"]
    contains_digits = bool(re.search(r"\d", raw_text))
    contains_math_words = any(w in norm_text for w in math_keywords)

    if contains_digits or contains_math_words:
        calc_success, calc_msg, raw_val = calculate(raw_text)
        if calc_success:
            logger.info("4. DETECTED INTENT: CALCULATOR")
            logger.info(f"5. EXTRACTED PARAMETERS: expression='{raw_text}'")
            logger.info("6. SELECTED ACTION: calculator.calculate()")
            logger.info(f"7. ACTION EXECUTION RESULT: Success=True, Response='{calc_msg}'")
            logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
            return CommandResult(
                raw_input=raw_text,
                normalized_input=norm_text,
                intent="CALCULATOR",
                response_text=calc_msg,
                should_exit=False,
                action_success=True
            )

    # 8. Local Knowledge base intent check
    know_success, know_ans = query_knowledge(raw_text)
    if know_success:
        logger.info("4. DETECTED INTENT: KNOWLEDGE")
        logger.info(f"5. EXTRACTED PARAMETERS: query='{raw_text}'")
        logger.info("6. SELECTED ACTION: knowledge.query_knowledge()")
        logger.info(f"7. ACTION EXECUTION RESULT: Success=True, Response='{know_ans}'")
        logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
        return CommandResult(
            raw_input=raw_text,
            normalized_input=norm_text,
            intent="KNOWLEDGE",
            response_text=know_ans,
            should_exit=False,
            action_success=True
        )

    # 9. Fallback unknown command handling
    logger.info("4. DETECTED INTENT: NONE (Command Unrecognized)")
    logger.info("5. EXTRACTED PARAMETERS: None")
    logger.info("6. SELECTED ACTION: Fallback UNKNOWN response")
    logger.info("7. ACTION EXECUTION RESULT: Rejected (No intent pattern matched)")
    logger.info("=== LIVE COMMAND PROCESSING TRACE END ===")
    return CommandResult(
        raw_input=raw_text,
        normalized_input=norm_text,
        intent="UNKNOWN",
        response_text="Sorry, I don't understand that command.",
        should_exit=False,
        action_success=False
    )

