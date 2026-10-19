from src.message_filter import MessageFilter

def test_user_reported_spam_messages():
    """Tests the exact spam patterns reported by the user."""
    spam_samples = [
        "44🔥",
        "46🔥",
        "48🔥",
        "50🔥",
        "52🔥",
        "54🔥",
        "56🔥",
        "58🔥",
        "60🔥",
        "24🔥",
        "26🔥",
        "28🔥",
        "30🔥",
        "**TARGET 1 DONE ✅**",
        "78🔥",
        "80🔥",
        "82🔥",
        "84🔥",
        "85🔥",
    ]

    for msg in spam_samples:
        should_process, reason = MessageFilter.should_process_message(msg)
        assert not should_process, f"Failed to filter spam message '{msg}', got reason: {reason}"

def test_variant_price_emoji_spam():
    """Tests variations of hype messages with multiple emojis, spaces, and currencies."""
    variants = [
        "44 🔥🔥🔥",
        "₹44🔥",
        "52.50 🚀",
        "60 BOOM 🔥",
        "85+ BLAST💥",
        "120 🎯",
        "Target 1 Done 🎯",
        "TARGET 2 HIT 🔥",
        "BOOM BLAST 🔥🚀",
        "🔥🔥🔥",
        "44",
        "78",
    ]

    for msg in variants:
        should_process, reason = MessageFilter.should_process_message(msg)
        assert not should_process, f"Failed to filter variant spam '{msg}', got reason: {reason}"

def test_legitimate_trading_signals_pass():
    """Ensures legitimate signals pass through to Gemini."""
    legit_signals = [
        "NIFTY 24050 CE ABV 44 TGT 52/60/70 SL 37",
        "NIFTY 24000 PE ABV 24 TGT 30/38/45 SL 18",
        "NIFTY 23800 PE ABV 78 SL 70 TGT 87,95,100+",
        "BANKNIFTY 52000 PE BUY ABOVE 320 SL 280 TGT 400",
        "BUY SENSEX 80000 CE @ 250 SL 200 TARGET 350",
        "FINNIFTY 23500 CE CMP 110 SL 90 TGT 140",
    ]

    for msg in legit_signals:
        should_process, reason = MessageFilter.should_process_message(msg)
        assert should_process, f"Legitimate signal was incorrectly filtered: '{msg}', reason: {reason}"

def test_order_modification_and_exits_pass():
    """Ensures crucial order management calls are never filtered out."""
    mgmt_calls = [
        "TRAIL SL TO 130",
        "TRAIL SL NIFTY 24050 CE TO 50",
        "REVISE SL TO 40",
        "EXIT NIFTY 24050 CE",
        "CANCEL NIFTY ORDER",
        "BOOK 50% PROFIT HERE",
        "CLOSE POSITION",
    ]

    for msg in mgmt_calls:
        should_process, reason = MessageFilter.should_process_message(msg)
        assert should_process, f"Management call was incorrectly filtered: '{msg}', reason: {reason}"
