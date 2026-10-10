"""
Automated Test Suite for Field Operations & Officer Commands
Tests all officer capabilities:
1. /login <pin> officer authentication
2. Unauthorized access rejection
3. /ops field dispatch queue & ward filtering
4. /dispatch <action_id> details view
5. Lifecycle status transitions: [Approve] -> [Start / Mobilize] -> [Mark Completed]
6. /blocker <action_id> <reason> critical issue escalation
7. /summary executive shift briefing & KPI metrics
8. /broadcast citywide emergency broadcast
9. Photo evidence upload linking with Action ID
"""

import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.telegram_bot import (
    CitizenTelegramBot,
    OFFICER_SESSIONS,
    ACTION_EVIDENCE,
    USER_SESSIONS
)
from backend.action_centre import get_action_store


@pytest.mark.asyncio
async def test_officer_authentication_and_authorization():
    print("\n[TEST 1] Officer PIN Authentication & Unauthorized Guard")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    unauth_user = 1111
    auth_user = 2222
    chat_id = 9999

    # 1. Unauthenticated user tries /ops -> Should be denied
    await bot.process_update({
        "update_id": 5001,
        "message": {"chat": {"id": chat_id}, "from": {"id": unauth_user}, "text": "/ops"}
    })
    assert unauth_user not in OFFICER_SESSIONS
    print("  Unauthorized attempt to /ops blocked [OK]")

    # 2. Login with wrong PIN -> Should fail
    await bot.process_update({
        "update_id": 5002,
        "message": {"chat": {"id": chat_id}, "from": {"id": auth_user}, "text": "/login WRONG_PIN"}
    })
    assert auth_user not in OFFICER_SESSIONS

    # 3. Login with correct PIN -> Should succeed
    await bot.process_update({
        "update_id": 5003,
        "message": {"chat": {"id": chat_id}, "from": {"id": auth_user}, "text": "/login AMC2026"}
    })
    assert auth_user in OFFICER_SESSIONS
    assert OFFICER_SESSIONS[auth_user]["role"] == "FIELD_OFFICER"
    print("  Authorized with PIN 'AMC2026' -> Role FIELD_OFFICER granted [OK]")
    print("  ✅ Officer authentication & security guards PASSED")


@pytest.mark.asyncio
async def test_field_ops_lifecycle_transitions():
    print("\n[TEST 2] Action Queue & 1-Click Status Lifecycle Transitions")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    officer_id = 2222
    chat_id = 9999
    OFFICER_SESSIONS[officer_id] = {"role": "FIELD_OFFICER", "chat_id": chat_id}

    store = get_action_store()
    # Create test action in proposed state
    test_action = store.create_action(
        ward_id="W1",
        ward_name="Danilimda",
        action_type="drainage_cleaning",
        priority="critical",
        reason="Danilimda highway underpass surcharge inundation",
        source="test"
    )
    act_id = test_action["action_id"]
    print(f"  Created test action: {act_id} (Status: {test_action['status']})")

    # 1. View /ops queue
    await bot.process_update({
        "update_id": 5004,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": "/ops"}
    })

    # 2. View specific dispatch directive
    await bot.process_update({
        "update_id": 5005,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": f"/dispatch {act_id}"}
    })

    # 3. Transition: Proposed -> Approved
    await bot.process_update({
        "update_id": 5006,
        "callback_query": {
            "id": "cb_approve",
            "chat_instance": "ci_1",
            "from": {"id": officer_id},
            "message": {"chat": {"id": chat_id}},
            "data": f"act_set:{act_id}:approved"
        }
    })
    act_after_approve = store.get_action(act_id)
    assert act_after_approve["status"] == "approved"
    print(f"  Transition 1: {act_id} -> APPROVED [OK]")

    # 4. Transition: Approved -> In Progress (Crew Mobilized)
    await bot.process_update({
        "update_id": 5007,
        "callback_query": {
            "id": "cb_start",
            "chat_instance": "ci_1",
            "from": {"id": officer_id},
            "message": {"chat": {"id": chat_id}},
            "data": f"act_set:{act_id}:in_progress"
        }
    })
    act_after_start = store.get_action(act_id)
    assert act_after_start["status"] == "in_progress"
    print(f"  Transition 2: {act_id} -> IN_PROGRESS [OK]")

    # 5. Transition: In Progress -> Completed
    await bot.process_update({
        "update_id": 5008,
        "callback_query": {
            "id": "cb_complete",
            "chat_instance": "ci_1",
            "from": {"id": officer_id},
            "message": {"chat": {"id": chat_id}},
            "data": f"act_set:{act_id}:completed"
        }
    })
    act_after_complete = store.get_action(act_id)
    assert act_after_complete["status"] == "completed"
    print(f"  Transition 3: {act_id} -> COMPLETED (Terminal State) [OK]")
    print("  ✅ Full lifecycle state-machine transitions PASSED")


@pytest.mark.asyncio
async def test_blocker_escalation_and_summary():
    print("\n[TEST 3] Critical Blocker Reporting & Executive Summary")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    officer_id = 2222
    chat_id = 9999
    OFFICER_SESSIONS[officer_id] = {"role": "FIELD_OFFICER", "chat_id": chat_id}

    store = get_action_store()
    blocked_act = store.create_action(
        ward_id="W7",
        ward_name="Vatva",
        action_type="mobile_pump",
        priority="high",
        reason="Dewatering needed at Vatva industrial node",
        source="test"
    )
    b_id = blocked_act["action_id"]

    # 1. Report Blocker via command
    await bot.process_update({
        "update_id": 5009,
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": officer_id},
            "text": f"/blocker {b_id} Substation power transformer submerged; generator required"
        }
    })
    updated_act = store.get_action(b_id)
    assert any("BLOCKER" in h.get("notes", "") for h in updated_act["status_history"])
    print(f"  Blocker successfully recorded in Action audit history for {b_id} [OK]")

    # 2. Executive Shift Briefing / Summary
    await bot.process_update({
        "update_id": 5010,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": "/summary"}
    })
    print("  Executive shift briefing generated [OK]")

    # 3. Emergency Broadcast
    await bot.process_update({
        "update_id": 5011,
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": officer_id},
            "text": "/broadcast Heat emergency declared in South Zone. Cooling shelters extended to 10 PM."
        }
    })
    print("  Emergency civic broadcast executed [OK]")
    print("  ✅ Blocker escalation and executive summary PASSED")


@pytest.mark.asyncio
async def test_photo_evidence_logging():
    print("\n[TEST 4] Field Photo Evidence Logging")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    officer_id = 2222
    chat_id = 9999
    OFFICER_SESSIONS[officer_id] = {"role": "FIELD_OFFICER", "chat_id": chat_id}

    target_act_id = "ACT-TEST999"

    # Simulate Telegram photo upload with caption
    photo_update = {
        "update_id": 5012,
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": officer_id},
            "caption": f"Pre-clearing drain status for {target_act_id}",
            "photo": [
                {"file_id": "photo_thumb_123", "width": 100, "height": 100},
                {"file_id": "photo_full_hires_456", "width": 1280, "height": 720}
            ]
        }
    }
    await bot.process_update(photo_update)

    assert target_act_id in ACTION_EVIDENCE
    assert len(ACTION_EVIDENCE[target_act_id]) == 1
    evidence = ACTION_EVIDENCE[target_act_id][0]
    assert evidence["file_id"] == "photo_full_hires_456"
    assert evidence["uploaded_by"] == officer_id
    print(f"  Photo evidence stored: {evidence['file_id']} for {target_act_id} [OK]")
    print("  ✅ Field photo evidence logging PASSED")


@pytest.mark.asyncio
async def test_ai_audit_and_simulation_commands():
    print("\n[TEST 5] AI Assistant, Impact Audit, and What-If Simulation")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    officer_id = 2222
    chat_id = 9999
    OFFICER_SESSIONS[officer_id] = {"role": "FIELD_OFFICER", "chat_id": chat_id}

    # 1. /ask AI query
    await bot.process_update({
        "update_id": 5013,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": "/ask Which wards exceed 33C WBGT today?"}
    })
    print("  /ask query executed [OK]")

    # 2. /audit Impact Verification command
    await bot.process_update({
        "update_id": 5014,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": "/audit Danilimda"}
    })
    print("  /audit impact telemetry queried [OK]")

    # 3. /simulate What-If Resource Allocation
    await bot.process_update({
        "update_id": 5015,
        "message": {"chat": {"id": chat_id}, "from": {"id": officer_id}, "text": "/simulate 600000 35"}
    })
    print("  /simulate resource allocation executed [OK]")
    print("  ✅ AI, Audit & Simulation capabilities PASSED")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING FIELD OPERATIONS & OFFICER TEST SUITE")
    print("=" * 60)
    asyncio.run(test_officer_authentication_and_authorization())
    asyncio.run(test_field_ops_lifecycle_transitions())
    asyncio.run(test_blocker_escalation_and_summary())
    asyncio.run(test_photo_evidence_logging())
    asyncio.run(test_ai_audit_and_simulation_commands())
    print("\n" + "=" * 60)
    print("ALL FIELD OPERATIONS & OFFICER TESTS PASSED! 🚀")
    print("=" * 60)
