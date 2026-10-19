import re
from typing import Tuple

class MessageFilter:
    """
    Intelligent high-speed pre-filter for Telegram messages.
    Filters out price tracking hype ('44🔥', '46🔥'), target celebration spam ('TARGET 1 DONE ✅'),
    and non-trade noise BEFORE making expensive calls to Gemini AI.
    """

    # 1. Actionable modification/exit keywords that should ALWAYS pass through to Gemini
    ALWAYS_PASS_KEYWORDS = [
        "TRAIL", "REVISE", "MODIFY", "CANCEL", "EXIT", "CLOSE", 
        "BOOK PROFIT", "BOOK PARTIAL", "BOOK 50%", "SQUARE OFF"
    ]

    # 2. Known Index names in Indian markets
    INDEX_PATTERNS = [
        "NIFTY", "BANKNIFTY", "BANK NIFTY", "FINNIFTY", "FIN NIFTY", 
        "SENSEX", "MIDCPNIFTY", "MIDCP NIFTY", "BANKEX"
    ]

    # 3. Target celebration / promotional patterns to drop
    CELEBRATION_PATTERNS = [
        r"^(?:\*{1,2})?(?:TARGET|TGT|T\d)\s*(?:\d+)?\s*(?:DONE|HIT|ACHIEVED|ROCKING|COMPLETED)(?:\*{1,2})?.*$",
        r"^(?:BOOM|BLAST|JACKPOT|ROCKING|FIRE|SUPERB|DHAMAKA|DHAMAL)[\s!🔥🚀💥🎯⚡️✨]*$",
        r"^(?:BOOK\s+PROFIT\s+NOW|BOOK\s+HERE\s+GUYS|SAFE\s+TRADERS\s+BOOK|ENJOY\s+PROFIT).*$",
        r"^(?:JOIN\s+VIP|PREMIUM\s+MEMBER|ACCURACY\s+\d+|CONTACT\s+ADMIN|PAYMENT\s+PROOF).*$",
    ]

    # 4. Price update spam with emojis or simple hype words:
    # E.g.: "44🔥", "46 🔥🔥🔥", "48.50 🚀", "52 BOOM", "60+ 🔥"
    PRICE_EMOJI_PATTERN = re.compile(
        r"^\s*₹?\s*(\d+(?:\.\d+)?)\s*\+?\s*([🔥🚀💥🎯⚡️✨💃🕺🎉✅]|BOOM|BLAST|ROCKING|FIRE|WOW)+\s*$",
        re.IGNORECASE
    )

    # 5. Pure numbers with optional single punctuation (e.g. "44", "50", "44.")
    PURE_NUMBER_PATTERN = re.compile(r"^\s*₹?\s*\d+(?:\.\d+)?\+?\s*$")

    @classmethod
    def should_process_message(cls, text: str) -> Tuple[bool, str]:
        """
        Evaluates whether a message is worth sending to Gemini AI.

        Returns:
            (True, "VALID_SIGNAL_CANDIDATE") -> Process with Gemini
            (False, reason_description)      -> Skip Gemini, saving cost & latency
        """
        if not text:
            return False, "EMPTY_MESSAGE"

        cleaned = text.strip()
        upper = cleaned.upper()

        # Rule 0: Critical Trade Management Safety Bypass
        # If the message contains explicit management actions, always send to Gemini
        for keyword in cls.ALWAYS_PASS_KEYWORDS:
            if keyword in upper:
                return True, f"SAFETY_PASS_{keyword}"

        # Rule 1: Pure emoji or punctuation check
        # Remove whitespace and typical emojis/punctuation
        non_emoji_content = re.sub(r"[\s🔥🚀💥🎯⚡️✨💃🕺🎉✅❤️👍🙏\.\,\-\!\?\|\*\_]", "", cleaned)
        if not non_emoji_content:
            return False, "PURE_EMOJI_OR_PUNCTUATION"

        # Rule 2: Single price + emoji spam (e.g. '44🔥', '46🔥', '52.50 🚀', '60 BOOM')
        if cls.PRICE_EMOJI_PATTERN.match(cleaned):
            return False, "PRICE_TRACKING_EMOJI_SPAM"

        # Rule 3: Pure single number check (e.g. '44', '52')
        if cls.PURE_NUMBER_PATTERN.match(cleaned):
            return False, "ISOLATED_PRICE_NUMBER"

        # Rule 4: Target celebration spam (e.g. '**TARGET 1 DONE ✅**', 'BOOM 🔥')
        for pattern in cls.CELEBRATION_PATTERNS:
            if re.match(pattern, cleaned, re.IGNORECASE):
                return False, "TARGET_CELEBRATION_OR_PROMO"

        # Rule 5: Signal Candidate Structure Gate
        has_index = any(idx in upper for idx in cls.INDEX_PATTERNS)
        has_strike_option = bool(re.search(r"\b\d{4,5}\s*(?:CE|PE|CALL|PUT)\b", upper))
        has_trading_verbs = bool(re.search(r"\b(?:BUY|SELL|ABV|ABOVE|BELOW|BLW|CMP|SL|TGT|TARGET|ENTRY)\b", upper))

        # Check for multi-part trade continuations (e.g., 'abv 32', 'SL 25 TGT 40, 50, 60+')
        # These are split messages following an instrument call and need Gemini's history context!
        has_action_with_price = bool(re.search(r"\b(?:BUY|SELL|ABV|ABOVE|BELOW|BLW|CMP|SL|TGT|TARGET)\s*[:=]?\s*\d+", upper))

        # If it has an instrument alone, or with verbs, it is a candidate
        if has_index or has_strike_option:
            return True, "INSTRUMENT_IDENTIFIED"

        # If it has an action keyword with a price (like 'abv 32', 'sl 25', 'tgt 40'),
        # it is a continuation of a prior message in Gemini's context history!
        if has_action_with_price:
            return True, "TRADE_CONTINUATION_FRAGMENT"

        # Otherwise it's general commentary or chatter
        return False, "NON_ACTIONABLE_COMMENTARY"
