"""
Automated Test Suite for Citizen Telegram Bot Integration
Tests all citizen bot features:
1. /start command menu
2. /risk <ward> lookup with Combined Risk Engine
3. GPS location pin processing & nearest ward mapping
4. /shelters relief facility locator
5. Multilingual public advisories (/advisory en, gu, hi)
6. Interactive incident report flow (/report -> ward -> type -> description)
7. Ticket status tracking (/ticket)
8. FastAPI webhook endpoint (/api/telegram/webhook)
"""

import sys
import os
import asyncio
import pytest

# Ensure backend module is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.telegram_bot import (
    CitizenTelegramBot,
    get_citizen_telegram_bot,
    find_nearest_ward,
    find_nearest_shelters,
    calculate_haversine_distance,
    AMC_RELIEF_FACILITIES,
    CITIZEN_INCIDENTS,
    USER_SESSIONS
)
from fastapi.testclient import TestClient
from backend.main import app


def test_distance_and_spatial_lookups():
    print("\n[TEST 1] Distance & Spatial Nearest Ward/Shelter Lookups")
    # Test distance between Ahmedabad Municipal Corporation and Danilimda
    dist = calculate_haversine_distance(23.0225, 72.5714, 22.9862, 72.5833)
    assert 3.0 <= dist <= 6.0
    print(f"  Haversine distance (Central -> Danilimda): {dist} km [OK]")

    # Test GPS location near Behrampura
    nearest_ward = find_nearest_ward(23.0015, 72.5895)
    assert nearest_ward["ward_name"] == "Behrampura"
    print(f"  Nearest ward for coordinates (23.0015, 72.5895): {nearest_ward['ward_name']} [OK]")

    # Test shelter locator
    shelters = find_nearest_shelters(23.0015, 72.5895, limit=2)
    assert len(shelters) == 2
    assert shelters[0]["ward"] == "Behrampura"
    assert "distance_km" in shelters[0]
    print(f"  Closest shelter found: '{shelters[0]['name']}' at {shelters[0]['distance_km']} km [OK]")
    print("  ✅ Spatial and shelter lookups PASSED")


@pytest.mark.asyncio
async def test_bot_command_handlers():
    print("\n[TEST 2] Telegram Bot Command Handlers")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    
    # 1. /start command
    start_update = {
        "update_id": 1001,
        "message": {
            "chat": {"id": 9991},
            "from": {"id": 8881},
            "text": "/start"
        }
    }
    await bot.process_update(start_update)

    # 2. /risk Danilimda command
    risk_update = {
        "update_id": 1002,
        "message": {
            "chat": {"id": 9991},
            "from": {"id": 8881},
            "text": "/risk Danilimda"
        }
    }
    await bot.process_update(risk_update)

    # 3. GPS Location pin sharing
    location_update = {
        "update_id": 1003,
        "message": {
            "chat": {"id": 9991},
            "from": {"id": 8881},
            "location": {
                "latitude": 22.9862,
                "longitude": 72.5833
            }
        }
    }
    await bot.process_update(location_update)

    # 4. /shelters command
    shelter_update = {
        "update_id": 1004,
        "message": {
            "chat": {"id": 9991},
            "from": {"id": 8881},
            "text": "/shelters"
        }
    }
    await bot.process_update(shelter_update)

    # 5. Multilingual /advisory
    for lang in ["en", "gu", "hi"]:
        adv_update = {
            "update_id": 1005,
            "message": {
                "chat": {"id": 9991},
                "from": {"id": 8881},
                "text": f"/advisory {lang}"
            }
        }
        await bot.process_update(adv_update)

    print("  ✅ Core command handlers execution PASSED")


@pytest.mark.asyncio
async def test_citizen_incident_reporting_flow():
    print("\n[TEST 3] Interactive Incident Reporting Flow")
    bot = CitizenTelegramBot(token="TEST_SIMULATION_TOKEN")
    user_id = 7771
    chat_id = 9992

    # Step 1: User initiates /report
    await bot.process_update({
        "update_id": 2001,
        "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/report"}
    })
    assert user_id in USER_SESSIONS
    assert USER_SESSIONS[user_id]["awaiting_input"] == "ward"

    # Step 2: User sends ward name
    await bot.process_update({
        "update_id": 2002,
        "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "Danilimda"}
    })
    assert USER_SESSIONS[user_id]["ward"] == "Danilimda"
    assert USER_SESSIONS[user_id]["awaiting_input"] == "hazard_type"

    # Step 3: User selects hazard callback button
    await bot.process_update({
        "update_id": 2003,
        "callback_query": {
            "id": "cb_001",
            "chat_instance": "ci_001",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}},
            "data": "report_type_waterlogging"
        }
    })
    assert USER_SESSIONS[user_id]["hazard_type"] == "waterlogging"
    assert USER_SESSIONS[user_id]["awaiting_input"] == "description"

    # Step 4: User describes location details
    initial_ticket_count = len(CITIZEN_INCIDENTS)
    await bot.process_update({
        "update_id": 2004,
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": user_id},
            "text": "Deep water accumulation under the Danilimda highway flyover."
        }
    })

    # Assert ticket was created
    assert len(CITIZEN_INCIDENTS) == initial_ticket_count + 1
    newest_ticket_id = list(CITIZEN_INCIDENTS.keys())[-1]
    ticket = CITIZEN_INCIDENTS[newest_ticket_id]
    assert ticket["ward"] == "Danilimda"
    assert ticket["hazard_type"] == "waterlogging"
    assert "highway flyover" in ticket["description"]
    print(f"  Created Incident Ticket: {newest_ticket_id} (Linked AMC Action: {ticket['action_id']}) [OK]")

    # Step 5: Check ticket status
    await bot.process_update({
        "update_id": 2005,
        "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/ticket {newest_ticket_id}"}
    })
    print("  ✅ Incident reporting and tracking flow PASSED")


def test_fastapi_telegram_endpoints():
    print("\n[TEST 4] FastAPI Telegram Webhook & Status Endpoints")
    client = TestClient(app)

    # 1. Status endpoint
    res_status = client.get("/api/telegram/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "total_facilities" in data
    assert "webhook_url" in data
    print(f"  Telegram status: Facilities={data['total_facilities']}, Active Tickets={data['active_citizen_tickets']}")

    # 2. Facilities endpoint
    res_fac = client.get("/api/telegram/facilities")
    assert res_fac.status_code == 200
    assert len(res_fac.json()["facilities"]) >= 5
    print(f"  Relief Facilities endpoint returned {len(res_fac.json()['facilities'])} municipal havens")

    # 3. Webhook endpoint POST
    res_hook = client.post("/api/telegram/webhook", json={
        "update_id": 3001,
        "message": {
            "chat": {"id": 5555},
            "from": {"id": 4444},
            "text": "/risk Vatva"
        }
    })
    assert res_hook.status_code == 200
    assert res_hook.json() == {"status": "ok"}
    print("  Webhook POST test passed: status=ok")

    # 4. List Incidents endpoint
    res_inc = client.get("/api/telegram/incidents")
    assert res_inc.status_code == 200
    print(f"  Incidents endpoint returned {res_inc.json()['total']} active tickets")
    print("  ✅ FastAPI Telegram endpoints PASSED")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING CITIZEN TELEGRAM BOT AUTOMATED TEST SUITE")
    print("=" * 60)
    test_distance_and_spatial_lookups()
    asyncio.run(test_bot_command_handlers())
    asyncio.run(test_citizen_incident_reporting_flow())
    test_fastapi_telegram_endpoints()
    print("\n" + "=" * 60)
    print("ALL CITIZEN TELEGRAM BOT TESTS COMPLETED SUCCESSFULLY! 🎉")
    print("=" * 60)
