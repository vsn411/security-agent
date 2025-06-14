import os
import uuid
from dotenv import load_dotenv
from agents import Agent, Runner, handoff
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
import chainlit as cl

from session_utils import get_session, add_history
from security_guardian import SecurityGuardian

load_dotenv()

# ======================
# Specialist Agents
# ======================

hotel_agent = Agent(
    name="HotelAgent",
    instructions="""
You are a hotel booking assistant.
Given a destination, dates, and budget, suggest 2–3 suitable hotel options.
For each, include hotel name, nightly price, user rating, and location details.
Be factual, concise, and focus only on hotel stay arrangements.
Do NOT suggest sightseeing or activities list.
Always prefix your response with [HotelAgent].
"""
)

activities_agent = Agent(
    name="ActivitiesAgent",
    instructions="""
You are a local activity and tour guide assistant.
Given a destination and interests (like food, culture, nature), suggest 2–3 relevant activities or attractions.
For each, provide name, description, estimated price, and duration.
Do NOT suggest hotels or booking options.
Always prefix your response with [ActivitiesAgent].
"""
)

# ======================
# Coordinator Agent with Handoffs
# ======================

coordinator_instructions = f"""{RECOMMENDED_PROMPT_PREFIX}
You are a travel coordinator.
You must ALWAYS delegate user requests to the relevant specialist agent(s) using the available handoff tools.
- For hotel requests, DELEGATE to the hotel agent.
- For activity requests, DELEGATE to the activities agent.
- For both, DELEGATE to both and COMBINE their responses.
NEVER answer directly. If you are not delegating, you are making a mistake.
Always clearly mark each agent's response with [HotelAgent] or [ActivitiesAgent].
"""

travel_coordinator = Agent(
    name="TravelCoordinator",
    instructions=coordinator_instructions,
    handoffs=[
        handoff(hotel_agent),
        handoff(activities_agent)
    ]
)

# ======================
# Secure Delegation Flow
# ======================

guardian = SecurityGuardian()

async def secure_handoff_flow(user_id: str, user_input: str) -> str:
    # Pre-check input
    pre_check = await guardian.pre_check(user_id, user_input)
    if not pre_check.startswith("[APPROVED"):
        print("[DEBUG] SecurityAgent blocked or escalated the input.")
        return pre_check
    print("[DEBUG] SecurityAgent approved input.")

    # Session history management
    session = get_session(user_id)
    hist = session["history"]
    add_history(hist, "user", user_input)
    prompt = "\n".join([m["content"] for m in hist])
    print("[DEBUG] TravelCoordinator triggered with prompt:")
    print(prompt)

    # Run coordinator agent (which handles handoffs)
    try:
        result = await Runner.run(travel_coordinator, prompt)
    except Exception as e:
        print(f"[DEBUG] TravelCoordinator error: {e}")
        return f"System Error: {str(e)}"

    add_history(hist, "assistant", result.final_output)
    print("[DEBUG] TravelCoordinator output:", result.final_output)

    # Debug: Which specialist agent was triggered?
    if "[HotelAgent]" in result.final_output:
        print("[DEBUG] HotelAgent was triggered by TravelCoordinator.")
    if "[ActivitiesAgent]" in result.final_output:
        print("[DEBUG] ActivitiesAgent was triggered by TravelCoordinator.")

    # Post-check output
    post_check = await guardian.post_check(user_id, result.final_output)
    if not post_check.startswith("[APPROVED"):
        print("[DEBUG] SecurityAgent blocked or escalated the output.")
        return post_check
    print("[DEBUG] SecurityAgent approved output.")

    # Log delegation if coordinator handed off
    if "[HotelAgent]" in result.final_output or "[ActivitiesAgent]" in result.final_output:
        await guardian.log_delegation(user_id)

    return result.final_output

# ======================
# Chainlit UI Integration
# ======================

@cl.on_chat_start
async def on_chat_start():
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("history", [])

@cl.on_message
async def main(message: cl.Message):
    user_id = cl.user_session.get("session_id")
    user_input = message.content
    print(f"[DEBUG] Received user input: {user_input}")
    response = await secure_handoff_flow(user_id, user_input)
    # Remove approval tags for user display
    response = response.replace("[APPROVED]", "").replace("[APPROVED - delegation]", "")
    print(f"[DEBUG] Final response to user:\n{response}\n")
    await cl.Message(content=response.strip()).send()

# ======================
# To run: chainlit run main_v1.py
# ======================
