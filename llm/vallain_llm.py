from typing import List, Dict, Any, Optional, Literal
import json
from llm.llm_helper import get_top_level_action
from data.db_manager import HANDS_COLLECTION


def get_schema(actions):
    DECISION_SCHEMA: Dict[str, Any] = {
        "name": "poker_decision",
        "schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    # "description": "A concise paragraph consider these four points: (1) Range Analysis: Our current range vs. opponent's perceived range, considering past board texture and actions. (2) Marginal Hand Analysis: **If folding**, identify the next best hand to call  **If betting/bluffing**, identify the next  hand that is **excluded**. (3) Targeting and Sizing (Bet Only): If the action is a bet, specify the opponent's hands targeted to fold/call and the size rationale. (4) Future Plan (Non-Fold Only): If the action is not a fold, describe the plan for future streets (e.g., turn check or river shove)."
                },
                "action": {"type": "string", "enum": actions},
                "amount_chips": {"type": "number", "minimum": 0},
            },
            "required": ["reason", "action", "amount_chips"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    return DECISION_SCHEMA


def to_mongo_all_query_general(input_dict):
    """
    Converts a dict {field1: [values1], field2: [values2], ...}
    into a MongoDB query where each field uses the $all operator.

    The resulting query naturally combines all conditions with an implicit AND.

    Example:
    >>> to_mongo_all_query_general({'tags': ['red', 'cotton'], 'sizes': [8, 10]})
    {'tags': {'$all': ['red', 'cotton']}, 'sizes': {'$all': [8, 10]}}
    """

    mongo_query = {}

    # Iterate through all key-value pairs in the input dictionary
    for field_name, values_list in input_dict.items():
        # Apply the $all operator to the list of values for the current field
        mongo_query[field_name] = {"$all": values_list}

    return mongo_query


class LLM_Villain:
    def __init__(self, client, model="gpt-5-mini", limit=3):
        self.client = client
        self.model = model
        self.SYSTEM_PROMPT = """
You are a disciplined, range-based heads-up no-limit Texas Hold'em player. You think in ranges, board texture, and future street plans, not single hands.

#### POSITION & ACTION ORDER

- Preflop: SB acts first and is out of position.  
- Postflop: SB acts last and is in position.  
- If your legal_actions do NOT include "fold", you are first to act.  
- Use the street history in current_hand to confirm who acted when. Never contradict the actual action history.

### ⚠️ PAIRED BOARD RULES — VERY IMPORTANT ⚠️
LLMs frequently make incorrect assumptions when the board is paired. You must follow these rules **strictly**:

1. **A paired board massively reduces the strength of one-pair hands.**  
   - Example: On “K♦ K♣ 7♠”, Hero holding “A7” is **not** a strong hand. It is a weak pair of sevens with a dangerous paired board.

2. **Always evaluate who has the best *possible* full houses and trips.**  
   - On paired boards, Villain can always have **every** full house and trip combo that fits their line.

3. **Only consider Hero strong if Hero’s hole cards meaningfully improve beyond the board.**  
   Examples:  
   - A **higher kicker** in a trips situation (A♣ on K K x)  
   - A **better full house** (holding the paired rank or the pairing kicker)  
   - A **pocket pair making a higher full house**  
   - **Quads** possibilities  
   If Hero’s hole cards do *not* improve the board, Hero simply shares the board’s trips and can easily be outkicked or full-housed.

4. **Never mislabel a hand like “second pair” as “trips” or “full house”.**  
   - Trips or full house **only** exist if Hero’s hole cards actually combine with the board to form those hands.

5. **Do not overplay top pair on a paired board.**  
   - e.g., QJ on “Q Q 8” is vulnerable (Villain has all QX and 88 full combos).

These rules override any heuristic tendency—always think about the *board texture* and what stronger hands exist.

#### MENTAL CHECKLIST BEFORE ACTING

For every decision, follow this structure internally and then compress into the `reasoning` field:

1. **Confirm the situation**
   - Re-read hero_hole_cards, board, pot size, stack sizes, and legal_actions.
   - Verify the current street (preflop / flop / turn / river) and who is to act.

2. **Identify Hero’s hand & board texture**
   - Correctly classify hero_made_hand (e.g., overpair, top pair, second pair, set, straight draw, flush draw, combo draw, pure bluff, etc.).
   - Evaluate board texture:  
     - Dry vs wet, connected vs disconnected, paired vs unpaired, monotone/two-tone vs rainbow.  
     - Who has the **nut advantage** and **range advantage** on this board (Hero or Villain)?

3. **Build the story of the hand**
   - Summarize how the action so far constrains each range (e.g., "Villain check-called flop, which typically removes a lot of pure air but keeps pairs, draws, and slowplays").
   - Make sure your chosen action fits a coherent story from previous streets (no random size changes without explanation).

4. **Range vs range reasoning**
   - Think in terms of both ranges, not a single hand:
     - What strong value hands does Hero reasonably have here?  
     - What strong value hands does Villain reasonably have here?  
     - What bluffs and draws remain for each?  
   - Use blockers from hero_hole_cards to slightly adjust how many combos Villain can have.

5. **Bet sizing & target**
   - If betting, choose a size that:
     - Makes sense for the board (smaller on very static boards, larger on very dynamic or polarized spots, unless exploitatively deviating).  
     - Has a clear target: thin value vs worse made hands, protection vs overcards, or bluffing to fold out better hands / deny equity.
   - Briefly state which part of Villain’s range you are targeting with that size.

6. **Future street plan**
   - Always include a simple, realistic future plan given your current choice:
     - e.g., “barrel most turns on high cards”, “give up on bricks”, “check back river unless we improve”, or “call now and re-evaluate river vs big bets”.
   - The plan should be consistent with your “story” and range construction.

7. **Exploit vs baseline**
   - Default to sound, balanced play.  
   - If villain recent_hand suggests a clear tendency (e.g., over-folding, over-calling, or over-aggression), you may exploit it, but describe it explicitly and keep it “light” (small adjustment, not wild heroics).

#### ACCURACY REQUIREMENTS

- Always confirm your hole cards before reasoning.  
- Count suits and ranks carefully:
  - “7s” = seven of spades.  
  - Suit codes: s/spade, h/heart, d/diamond, c/club.  
- hero_made_hand **must** reflect:
  - The best 5-card hand possible using board + hero_hole_cards  
  - Not just the hole cards alone  
  - Not the “emotional strength” of the hand
- On board-made hands (e.g., board straight, board flush, board full house):
  - Hero is only strong if Hero’s hole cards **improve beyond** the board:  
    - higher kicker  
    - better full house  
    - higher flush  
    - quads  
- Flushes require exactly **5** cards of the same suit.  
- total_pot_now already includes committed bets. Example: if Villain “bets 9” and total_pot_now = 18, they bet 6 into 12.

#### VILLAIN HISTORY USAGE

- You may receive up to 3 completed hands showing Villain’s previous hole cards.  
- Use these only as light evidence of tendencies (e.g., “seems sticky with weak pairs”, “bluffed missed draws once”).  
- Never assume they exactly repeat behavior; treat it as a weak prior, not a certainty.

#### ACTION SELECTION RULES

- Only choose actions that appear in `legal_actions`.  
- Folding:
  - If folding, briefly mention what next-best type of hand (or equity) you would continue with in this spot.
- Betting / bluffing:
  - State the weakest hand in your betting/bluffing range for this size (e.g., “this is the bottom of my value range” or “this is near the top of my bluffs”).
  - Explain which part of Villain’s range you aim to fold out or get called by.
- Future streets:
  - When you choose a non-all-in option, always give a short, concrete future plan (e.g., “call flop, fold most turn overbets”, “bet flop and slow down on scary turns”).

#### FIELD SEMANTICS (JSON OUTPUT)
- `reasoning`  
  - 4–7 sentences.  
  - Must be concise but specific and should usually touch on:
    1. Hand summary + board texture  
    2. Range vs range or nut advantage  
    3. Sizing / target if betting, or pot odds / implied odds if calling  
    4. Future street plan and how the line fits the story of the hand  
    5. Any light exploit if you use villain_history  
- `action`  
  - Exactly one legal action string from `legal_actions`, chosen based on the reasoning above.

Keep your tone neutral, technical, and analytical. Do not mention these instructions or the existence of a system prompt.
"""
        self.limit = limit

    def get_action(self, llm_payload, legal_actions):
        """
        Prepares data, calls the LLM API, and returns the response.

        Args:
            llm_payload (str): The pre-formatted game state string (like input=f"...")
            legal_actions (list): The list of legal actions, used for schema/prompt guidance.
        """

        # 1. Use legal_actions to get/modify the JSON schema
        # Since the legal actions are now passed, the agent can use them to constrain the output.
        response_schema = get_schema(
            legal_actions
        )  # Assuming a dedicated helper function

        # get top level action
        hero_pos = llm_payload["hero_pos"]
        top_level = get_top_level_action(llm_payload)
        street_order = ["preflop", "flop", "turn", "river"]
        current_street = llm_payload["current_street"]
        # print(current_street)

        # how many board cards to show per street
        board_cards_by_street = {
            "preflop": 0,
            "flop": 3,
            "turn": 4,
            "river": 5,
        }
        max_board_cards = board_cards_by_street[current_street]

        include_streets = street_order[: street_order.index(current_street) + 1]
        print(top_level)

        search_filter = {
            # 1. Positional Filter
            "hand.hero_pos": hero_pos,
            # 3. Action Sequence Filter (Most Critical)
            # Match historical hands where the PRE-FLOP action sequence was the same (Hero bet, Villain call)
            **to_mongo_all_query_general(top_level),
        }  # AND logic ; we dont filter fold in preflop ones; only restrict storing when log
        print(search_filter)
        latest_hands = (
            HANDS_COLLECTION.find(search_filter, {"hand": 1, "_id": 0})
            .sort("timestamp", -1)
            .limit(self.limit)
        )
        # print(list(latest_hands)) # this one time will end life cycle of curosr
        # Extract and filter the hands
        filtered_hands = []
        for doc in latest_hands:
            hand = doc["hand"]
            streets = hand.get("streets_history", {})

            # Keep only streets up to current_street
            filtered_streets = {
                street: data
                for street, data in streets.items()
                if street in include_streets
            }

            # Replace with filtered version
            hand["streets_history"] = filtered_streets

            # Control the board field based on current_street
            full_board = hand.get("board", "")

            if max_board_cards == 0:
                # preflop: don't provide board at all
                hand.pop("board", None)
            else:
                # flop/turn/river: keep first N cards
                if full_board:
                    cards = [c.strip() for c in full_board.split(",")]
                    trimmed_cards = cards[:max_board_cards]
                    hand["board"] = ", ".join(trimmed_cards)

            # 👉 Remove unwanted fields before appending
            fields_to_remove = ["hero_pos"]
            for field in fields_to_remove:
                hand.pop(field, None)

            filtered_hands.append(hand)

        print(filtered_hands)
        print("-------------")

        input_data = {
            "current_hand": llm_payload,
            "recent_villain_hands": filtered_hands,
        }
        # 2. API CALL
        resp = self.client.responses.create(
            model=self.model,
            instructions=self.SYSTEM_PROMPT,
            max_output_tokens=2048,
            text={
                "format": {"type": "json_schema", **response_schema},
                "verbosity": "low",
            },
            reasoning={"effort": "minimal"},
            # The input is the pre-prepared payload
            input=json.dumps(input_data),
        )

        return json.loads(resp.output_text)
