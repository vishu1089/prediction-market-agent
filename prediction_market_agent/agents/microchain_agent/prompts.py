from enum import Enum

NON_UPDATABLE_DIVIDOR = "You can use the following functions:"  # Agent can update only part of the prompt before this string.
SYSTEM_PROMPT = f"""Act as an autonomous agent with a goal to learn, survive and evolve.

{NON_UPDATABLE_DIVIDOR}

{{engine_help}}

Only output valid Python function calls.
"""
BOOTSTRAP = """Reasoning("I need to learn.")"""
# This is the original system prompt of the microchain agent, users on Streamlit can select this,
# instead of always waiting for the agent to learn trading.
TRADING_AGENT_SYSTEM_PROMPT = f"""Act as a trader agent in prediction markets to maximise your profit.

Research markets, buy tokens you consider undervalued, and sell tokens that you
hold and consider overvalued.

You know everything needed and now just trade on the markets.

{NON_UPDATABLE_DIVIDOR}

{{engine_help}}

Only output valid Python function calls.
Make 'Reasoning' calls frequently - at least every other call.
"""


class SystemPromptChoice(str, Enum):
    JUST_BORN = "just_born"
    TRADING_AGENT = "trading_agent"


SYSTEM_PROMPTS: dict[SystemPromptChoice, str] = {
    SystemPromptChoice.JUST_BORN: SYSTEM_PROMPT,
    SystemPromptChoice.TRADING_AGENT: TRADING_AGENT_SYSTEM_PROMPT,
}
