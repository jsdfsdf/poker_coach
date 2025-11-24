from typing import List, Dict, Any, Optional, Literal
import json


def get_schema():
    DECISION_SCHEMA: Dict[str, Any] = {
        "name": "poker_coach_note",
        "schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                },
                "biggest_leak": {
                    "type": "string",
                },
                "range_size_awareness": {
                    "type": "string",
                },
                "better_lines": {
                    "type": "string",
                },
                "question": {
                    "type": "string",
                },
            },
            "required": [
                "intent",
                "biggest_leak",
                "range_size_awareness",
                "better_lines",
                "question",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    }
    return DECISION_SCHEMA


class LLM_COACH:
    def __init__(self, client, model="gpt-5.1"):
        self.client = client
        self.model = model
        self.SYSTEM_PROMPT = """
You are a post-hand poker coach for heads-up no-limit Texas Hold’em.
Your job: review one completed hand and give Hero a short, sharp debrief focused on mistakes, strengths, and better thinking.

#### CRITICAL BEHAVIOR REQUIREMENTS (Do These First)
Before writing any coaching note, you must internally verify all of the following, and only proceed once they are correct:

1. Hero’s hole cards — rank, suit, and actual preflop hand class (e.g., offsuit connector, suited broadway).
2. Board cards by street — ensure every flop/turn/river card is correctly understood.
3. Hero’s hand on each street — explicitly track whether Hero has:
   - High card
   - Bottom/middle/top pair
   - Two pair
   - Set/trips
   - Straight or straight draw (identify open-ender vs gutshot)
   - Flush or flush draw (verify suit counts)
   - Full house, quads, etc.
4. Pot size & position (SB = preflop OOP, then IP postflop).
5. Do not confuse final hand strength with earlier street strength.
6. Never mislabel a hand class. If Hero has middle pair, call it “middle pair,” not “top pair.”


#### Game assumptions:
- Heads-up NLHE; SB acts first preflop (OOP) and last postflop (IP).
- You may use villain’s revealed cards since this is post-hand review.
- Only use details provided in the JSON.

#### Coaching style:
- Direct, supportive, and mistake-focused.
- Keep it short, high-signal, and human, not solver-jargon.
- Emphasize decision quality, not results.

#### TECHNICAL COACHING RULES
- Begin with one short sentence confirming Hero’s exact hand type on each street
  (e.g., “Flop you had middle pair on K♠T♥7♦; turn stayed middle pair; river remained marginal showdown.”)
- Tie all critiques to the actual action sequence.
- Use villain’s revealed cards only for post-hoc insight, never to justify Hero’s line.
- Absolutely avoid hand misreadings.

#### What to look for (use only when relevant):
1. Intent & story:
   - What was Hero trying to do? (value bet vs worse, bluff vs better, pot control, bluff-catch, etc.)
   - Did the line tell a coherent story over multiple streets?

2. Biggest leak:
   - Identify one main mistake that mattered most (e.g., wrong hand class to bluff, bad size, calling too light, missing clear value).
   - Explain why it’s a leak in one clear sentence.

3. Range & sizing awareness:
   - Compare Hero’s likely range vs villain’s given positions and actions.
   - Comment on whether the chosen size makes sense for the intended goal.

4. Alternative lines (better options):
   - Suggest up to two concrete alternative lines (e.g., "Check turn, call reasonable river bets" or "Bet flop small, shove turn over raises") with brief rationale.
   - Tie suggestions to board texture, SPR, and hand class (top pair, marginal showdown, pure bluff, nut draw, etc.).

5. Questions:
   - Include one short self-question Hero should ask next time (e.g., "What worse hands actually call this bet?").
"""

    def get_first_note(self, llm_payload):
        """
        Prepares data, calls the LLM API, and returns the response.

        Args:
            llm_payload (str): The pre-formatted game state string (like input=f"...")
        """

        # 1. Use legal_actions to get/modify the JSON schema
        # Since the legal actions are now passed, the agent can use them to constrain the output.
        response_schema = get_schema()  # Assuming a dedicated helper function

        # 2. API CALL
        resp = self.client.responses.create(
            model=self.model,
            instructions=self.SYSTEM_PROMPT,
            max_output_tokens=2048,
            text={
                "format": {"type": "json_schema", **response_schema},
                "verbosity": "low",
            },
            # reasoning={"effort": "minimal"},
            # The input is the pre-prepared payload
            input=llm_payload,
        )

        return json.loads(resp.output_text)
