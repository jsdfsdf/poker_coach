"""
PokerKit adapter for heads-up Texas Hold'em.

Provides a clean interface to PokerKit with methods for:
- Starting new hands
- Getting legal actions
- Applying actions
- Checking terminal state
- Retrieving serializable state
"""

from typing import Dict, List, Optional, Tuple, Any
import random
import yaml
from pokerkit import (
    NoLimitTexasHoldem,
    Automation,
    StandardHighHand,
)
from pokerkit.state import (
    BoardDealing,
    Folding,
    CheckingOrCalling,
    CompletionBettingOrRaisingTo,
)
from llm.vallain_llm import LLM_Villain
from llm.coach_llm import LLM_COACH
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Literal
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

# from dotenv import load_dotenv
# load_dotenv()

from llm.llm_helper import filter_dict_keys
import json
import re
import os
import streamlit as st


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml.

    Returns:
        Configuration dictionary

    Example:
        >>> config = load_config()
        >>> config['game']['big_blind']
        10
    """
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


class PokerGame:
    """Heads-up Texas Hold'em game engine using PokerKit.

    Manages game state, player stacks, and action history.
    Player 0 is Hero, Player 1 is Villain (AI opponent).
    hero - human
    """

    def __init__(self):
        """Initialize game with config settings."""
        self.config = load_config()
        self.small_blind = self.config["game"]["small_blind"]
        self.big_blind = self.config["game"]["big_blind"]
        self.starting_stack = self.config["game"]["starting_stack"]

        # Game state
        self.hero_stack = self.starting_stack
        self.villain_stack = self.starting_stack
        self.hero_index = 0  # start as SB  - 0 BB 1 SB
        self.state = None
        self.hand_history: List[Dict[str, Any]] = []
        self.hand_complete = False
        self.hero_cards: Optional[Tuple[str, str]] = None
        self.villain_cards: Optional[Tuple[str, str]] = None
        self.board_cards: List[str] = []
        self.current_street = "preflop"

        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
        self.openai_client = OpenAI()
        self.villain_llm = LLM_Villain(self.openai_client)
        self.coach_llm = LLM_COACH(self.openai_client)
        self.llm_decisions = []

    def new_hand(self) -> None:
        """Start a new hand.

        Deals cards, posts blinds, and initializes hand history.
        Hero is small blind/button, Villain is big blind.

        Example:
            >>> game = PokerGame()
            >>> game.new_hand()
            >>> game.hand_complete
            False
        """
        self.hero_index += 1
        self.hero_index = self.hero_index % 2

        # Alternate button position (hero starts as button/SB)
        self.llm_decisions = []
        self.hand_history = []
        self.hand_complete = False
        self.board_cards = []
        self.current_street = "preflop"

        stacks_seat_order = (
            (self.hero_stack, self.villain_stack)
            if self.hero_index == 0
            else (self.villain_stack, self.hero_stack)
        )

        # Create new hand
        automations = (
            Automation.ANTE_POSTING,
            Automation.BET_COLLECTION,
            Automation.BLIND_OR_STRADDLE_POSTING,
            Automation.CARD_BURNING,
            Automation.HOLE_DEALING,
            Automation.BOARD_DEALING,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
            Automation.HAND_KILLING,
            Automation.CHIPS_PUSHING,
            Automation.CHIPS_PULLING,
        )
        self.state = NoLimitTexasHoldem.create_state(
            automations=automations,
            ante_trimming_status=False,  # no special trimming
            raw_antes=0,  # no antes
            raw_blinds_or_straddles=(
                self.small_blind,
                self.big_blind,
            ),  # (small blind, big blind)
            min_bet=self.big_blind,  # min bet = big blind
            raw_starting_stacks=stacks_seat_order,
            player_count=2,
        )

        # Extract hole cards
        if self.state.hole_cards and len(self.state.hole_cards) == 2:
            self.villain_cards = re.sub(
                r"[\[\]]", "", str(self.state.hole_cards[1 - self.hero_index])
            )
            self.hero_cards = re.sub(
                r"[\[\]]", "", str(self.state.hole_cards[self.hero_index])
            )

        # Log blind posting
        # self.hand_history.append(
        #     {
        #         "street": "preflop",
        #         "player": "hero",
        #         "action": "post_sb",
        #         "amount": self.small_blind,
        #         "pot": self.small_blind,
        #     }
        # )
        # self.hand_history.append(
        #     {
        #         "street": "preflop",
        #         "player": "villain",
        #         "action": "post_bb",
        #         "amount": self.big_blind,
        #         "pot": self.small_blind + self.big_blind,
        #     }
        # )

    def legal_actions(self) -> List[str]:
        """Get list of legal actions for current player.

        Returns:
            List of action names: ['fold', 'check', 'call', 'bet', 'raise']
               CompletionBettingOrRaisingTo  check_or_call
        Example:
            >>> game = PokerGame()
            >>> game.new_hand()
            >>> actions = game.legal_actions()
            >>> 'fold' in actions
            True
        """
        if self.hand_complete or not self.state:
            return []

        actions = []

        # Check if can fold
        if self.state.can_fold():
            actions.append("fold")

        # Check if can check/call
        if self.state.can_check_or_call():
            if self.state.checking_or_calling_amount == 0:
                actions.append("check")
            else:
                actions.append("call")

        # Check if can bet/raise
        if self.state.can_post_bring_in() or self.state.can_complete_bet_or_raise_to():
            # Get min/max bet amounts
            min_bet = self.state.min_completion_betting_or_raising_to_amount
            max_bet = self.state.max_completion_betting_or_raising_to_amount

            if min_bet is not None and max_bet is not None and min_bet <= max_bet:
                if self.state.completion_betting_or_raising_count == 0:
                    # First action is a bet
                    actions.append("bet")
                else:
                    actions.append("raise")

        return actions

    def get_bet_range(self) -> Tuple[Optional[int], Optional[int]]:
        """Get minimum and maximum bet/raise amounts.

        Returns:
            Tuple of (min_amount, max_amount) or (None, None) if betting not available
        """
        if not self.state or self.hand_complete:
            return (None, None)

        if self.state.can_post_bring_in() or self.state.can_complete_bet_or_raise_to():
            min_amt = self.state.min_completion_betting_or_raising_to_amount
            max_amt = self.state.max_completion_betting_or_raising_to_amount
            return (min_amt, max_amt)

        return (None, None)

    def apply_action(self, action: str, amount: Optional[int] = None) -> None:
        """Apply an action to the game state.

        Args:
            action: One of 'fold', 'check', 'call', 'bet', 'raise'
            amount: Bet/raise amount (required for bet/raise)

        Raises:
            ValueError: If action is illegal or amount is invalid

        Example:
            >>> game = PokerGame()
            >>> game.new_hand()
            >>> game.apply_action('call')
        """
        if self.hand_complete or not self.state:
            raise ValueError("Hand is complete, cannot apply action")

        legal = self.legal_actions()
        if action not in legal:
            game_state = to_llm_state(self.state, 1 - self.hero_index)
            llm_payload = game_state.to_model_payload()
            # logger.warning(f"llm state {llm_payload}")
            raise ValueError(f"Action {action} not legal. Legal actions: {legal}")

        # Determine current player
        # actor_index = self.state.actor_index
        # player_name = "hero" if actor_index == 0 else "villain"

        # Execute action
        if action == "fold":
            self.state.fold()
            # self.hand_history.append(
            #     {
            #         "street": self.current_street,
            #         "player": player_name,
            #         "action": "fold",
            #         "amount": 0,
            #         "pot": self.state.total_pot_amount,
            #     }
            # )
            self.hand_complete = True

        elif action == "check":
            self.state.check_or_call()
            # self.hand_history.append(
            #     {
            #         "street": self.current_street,
            #         "player": player_name,
            #         "action": "check",
            #         "amount": 0,
            #         "pot": self.state.total_pot_amount,
            #     }
            # )

        elif action == "call":
            # call_amount = self.state.checking_or_calling_amount
            self.state.check_or_call()
            # self.hand_history.append(
            #     {
            #         "street": self.current_street,
            #         "player": player_name,
            #         "action": "call",
            #         "amount": call_amount,
            #         "pot": self.state.total_pot_amount,
            #     }
            # )

        elif action in ("bet", "raise"):
            if amount is None:
                raise ValueError(f"{action} requires an amount")

            min_amt, max_amt = self.get_bet_range()
            if min_amt is None or max_amt is None:
                raise ValueError(f"Cannot {action} in current state")

            if amount < min_amt or amount > max_amt:
                raise ValueError(
                    f"{action} amount {amount} outside valid range [{min_amt}, {max_amt}]"
                )

            self.state.complete_bet_or_raise_to(amount)
            # self.hand_history.append(
            #     {
            #         "street": self.current_street,
            #         "player": player_name,
            #         "action": action,
            #         "amount": amount,
            #         "pot": self.state.total_pot_amount,
            #     }
            # )

        # Update street if changed
        # self._update_street()

        # Check if hand is terminal
        if self.state.status is False:
            self.hand_complete = True
            self._update_stacks()

    def _update_street(self) -> None:
        """Update current street based on board cards."""
        if not self.state:
            return

        board = self.state.board_cards
        if board:
            self.board_cards = [str(card) for card in board]
            num_board = len(self.board_cards)
            if num_board == 3:
                self.current_street = "flop"
            elif num_board == 4:
                self.current_street = "turn"
            elif num_board == 5:
                self.current_street = "river"

    def _update_stacks(self) -> None:
        """Update player stacks after hand completion."""
        if self.state and len(self.state.stacks) == 2:
            self.hero_stack = self.state.stacks[self.hero_index]
            self.villain_stack = self.state.stacks[1 - self.hero_index]

    def is_terminal(self) -> bool:
        """Check if hand is complete.

        Returns:
            True if hand has ended (fold or showdown), False otherwise

        Example:
            >>> game = PokerGame()
            >>> game.new_hand()
            >>> game.is_terminal()
            False
        """
        return self.hand_complete

    def get_current_player(self) -> Optional[str]:
        """Get current player to act.

        Returns:
            'hero', 'villain', or None if hand is complete
        """
        if self.hand_complete or not self.state:
            return None

        actor_index = self.state.actor_index
        return "hero" if actor_index == self.hero_index else "villain"

    def get_state_dict(
        self, hero_index, reveal: bool = False, add_reason: bool = False
    ) -> Dict[str, Any]:
        """Get serializable game state.

        Args:
            reveal: If True, include both players' hole cards

        Returns:
            Dictionary with game state including:
            - players: list of player names
            - stacks: current stack sizes
            - street: current betting round
            - board: community cards
            - pot: total pot amount
            - actions: hand history
            - hole_cards: player cards (if reveal=True)

        Example:
            >>> game = PokerGame()
            >>> game.new_hand()
            >>> state = game.get_state_dict()
            >>> 'pot' in state
            True
        """
        # state = {
        #     "players": ["hero", "villain"],
        #     "stacks": {"hero": self.hero_stack, "villain": self.villain_stack},
        #     "street": self.current_street,
        #     "board": self.board_cards,
        #     "pot": self.state.total_pot_amount if self.state else 0,
        #     "actions": self.hand_history,
        #     "current_player": self.get_current_player(),
        #     "is_terminal": self.hand_complete,
        # }

        # call my helper
        game_state = to_llm_state(self.state, hero_index)

        state = game_state.to_model_payload()

        if reveal and self.hero_cards and self.villain_cards:
            state["hole_cards"] = {
                "hero": self.hero_cards,
                "villain": self.villain_cards,  # hole cards disppar after game end
            }
        if add_reason:  # human is hero
            llm_idx = 0
            for street, street_data in state["streets_history"].items():
                for action_detail in street_data["actions"]:
                    # Extract variables from the current action dictionary
                    player = action_detail["actor"]
                    if (
                        player == "Villain" and self.llm_decisions
                    ):  # our street history give V not villain
                        action_detail["llm_reason"] = self.llm_decisions[llm_idx]
                        llm_idx += 1
        return state

    def villian_llm_action(self) -> None:
        """Execute llm"""
        if self.get_current_player() != "villain":
            return

        legal = self.legal_actions()
        if not legal:
            return

        #
        game_state = to_llm_state(self.state, 1 - self.hero_index)
        resp = self.villain_llm.get_action(
            llm_payload=game_state.to_model_payload(), legal_actions=legal
        )
        # resp = get_llm_action(self.client, game_state.to_model_payload(), legal)
        # print(resp)
        action, amt = resp["action"], resp["amount_chips"]
        # logger.warning("villian_llm_action %s", action)
        self.llm_decisions.append(resp["reason"])
        if action in ["check", "fold", "call"]:
            self.apply_action(action)
        else:
            min_amt, max_amt = self.get_bet_range()
            amt = min(max(min_amt, amt), max_amt)
            self.apply_action(action, amt)

    def villain_action(self) -> None:
        """Execute random action for villain (simple AI).

        Villain makes random legal moves for MVP.
        """
        if self.get_current_player() != "villain":
            return

        legal = self.legal_actions()
        if not legal:
            return

        # Simple random strategy
        # Fold 20%, Check/Call 50%, Bet/Raise 30%
        rand = random.random()

        if "fold" in legal and rand < 0.2 and "check" not in legal:
            self.apply_action("fold")
        elif "check" in legal and rand < 0.7:
            self.apply_action("check")
        elif "call" in legal and rand < 0.7:
            self.apply_action("call")
        elif "bet" in legal:
            min_amt, max_amt = self.get_bet_range()
            if min_amt and max_amt:
                # Random bet between min and pot-sized
                pot_bet = min(max_amt, self.state.total_pot_amount)
                bet_amt = random.randint(min_amt, max(min_amt, pot_bet))
                self.apply_action("bet", bet_amt)
        elif "raise" in legal:
            min_amt, max_amt = self.get_bet_range()
            if min_amt and max_amt:
                # Random raise
                raise_amt = random.randint(min_amt, max(min_amt, min_amt * 2))
                self.apply_action("raise", raise_amt)
        elif "check" in legal:
            self.apply_action("check")
        elif "call" in legal:
            self.apply_action("call")
        elif legal:
            # Fallback to first legal action
            self.apply_action(legal[0])

    def get_coach_note(self):
        hand_dict = self.get_state_dict(
            hero_index=self.hero_index,
            reveal=True,
            add_reason=False,
        )
        hand_dict["start_effective_stack"] = min(self.state.starting_stacks)
        to_keep = [
            "hero_pos",
            "board",
            "streets_history",
            "start_effective_stack",
            "big_blind",
            "hole_cards",
        ]
        hand_dict = filter_dict_keys(hand_dict, to_keep)
        resp = self.coach_llm.get_first_note(json.dumps(hand_dict))
        return resp


@dataclass(frozen=True)
class LLMState:
    # Required for decision making
    # hero_seat: int  # 0/1 no longer need becasue we translate to hero_pos
    big_blind: int
    hero_pos: str
    position_role: str
    hero_stack: int
    villain_stack: int
    hero_hand: str  # ["9s","8c"] or None (mask if needed)
    board: str
    hero_made_hand: str
    current_street: str
    streets_history: Dict[str, Any]  # Trimmed, normalized
    total_pot_now: int
    legal_actions: List[str]
    # villain_hand: str = "" # no LLM dont need this

    def to_model_payload(self) -> Dict[str, Any]:
        """
        Produce the minimal, JSON-safe dict the LLM sees.
        """
        d = asdict(self)
        # You can drop high-cardinality fields here if needed
        return d


def street_index_to_name(state):
    street_index = state.street_index
    if street_index == 0:
        return "preflop"
    elif street_index == 1:
        return "flop"
    elif street_index == 2:
        return "turn"
    elif street_index == 3:
        return "river"
    return "end"


def get_pos(index):
    # 0 is big blidn 1 is small blind
    if index:
        return "SB"
    return "BB"


def get_in_out_pos(street_index, pos):
    """
    street_index 0 preflop, pos either BB or SB
    IP OOP
    """
    if street_index == 0:
        if pos == "SB":
            return "OOP"
        return "IP"
    else:
        if pos == "SB":
            return "IP"
        return "OOP"


def to_llm_state(state, ai_index) -> LLMState:
    """
    Read PokerKit and build an immutable LLMState.
    Replace the engine.* calls with your real PokerKit API.
    ai_index heor version
    """
    # --- Replace these with PokerKit getters ---
    # get hand type
    hole = state.hole_cards[ai_index]
    board = [i[0] for i in state.board_cards]
    if street_index_to_name(state) not in ["preflop", "end"]:
        hand = StandardHighHand.from_game(hole, board)
        # hand_type = str(hand.entry.label)
    else:
        hand = ""
        # print(street_index_to_name(state))

    # HOLE CARDS (mask if simulating villain’s turn or running evals)
    ai_hand = re.sub(r"[\[\]]", "", str(state.hole_cards[ai_index]))

    # ACTION HISTORY (normalize and trim)
    streets = streets_from_state(state, ai_index)
    # narrative = f"You are player {ai_index},  {street_index_to_name(state)} action on you"
    # actions.append(narrative)
    legal_actions = stete_to_actions(state)

    pos = get_pos(ai_index)

    return LLMState(
        # hero_seat=ai_index,
        big_blind=state.blinds_or_straddles[1],
        hero_pos=pos,
        position_role=get_in_out_pos(state.street_index, pos),
        hero_stack=state.stacks[ai_index],
        villain_stack=state.stacks[1 - ai_index],
        hero_hand=ai_hand,
        board=re.sub(r"[\[\]]", "", str(state.board_cards)),
        hero_made_hand=str(hand),
        current_street=street_index_to_name(state),
        streets_history=streets,
        total_pot_now=state.total_pot_amount,
        legal_actions=legal_actions,
    )


def streets_from_state(state, hero_index):
    # 1. Initialize result structure and street tracking
    result = {}

    streets = ["preflop", "flop", "turn", "river"]
    current_street_index = 0
    current_board_cards = []
    # hero_index = 0

    # Helper function to determine actor name
    def get_actor(player_index: int) -> str:
        return "Hero" if player_index == hero_index else "Villain"

    # Helper function to get the current street dict
    def get_current_street_dict(current_street_index):
        street = streets[current_street_index]
        if street in result:
            return result[street]
        else:
            result[street] = {"actions": []}
            return result[street]

    current_bet = 0
    # 2. Iterate through operations and process
    for op in state.operations:

        # Process board dealing (street change)
        if isinstance(op, BoardDealing):
            # Move to the next street
            current_street_index += 1
            current_bet = 0
            if current_street_index >= len(streets):
                # Should not happen in standard Texas Hold'em
                raise

        if isinstance(op, (Folding, CheckingOrCalling, CompletionBettingOrRaisingTo)):
            actor_name = get_actor(op.player_index)
            amt = getattr(op, "amount", 0)
            if isinstance(op, Folding):
                action = "fold"
            elif isinstance(op, CheckingOrCalling):
                # Player has already put this much in on this street
                if amt == 0:
                    # No bet to match → it's a check
                    action = "check"
                else:
                    # Calling an existing bet
                    action = "call"
            elif isinstance(op, CompletionBettingOrRaisingTo):
                if current_bet == 0:
                    action = "bet"
                    current_bet += 1
                else:
                    action = "raise"

            # action = str(op).split("(", 1)[0]

            # 3. Append the action to the current street
            current_street_dict = get_current_street_dict(current_street_index)
            current_street_dict["actions"].append(
                {"actor": actor_name, "action": action, "amt": amt}
            )

    # add villain actions
    # for (
    #     street,
    #     data,
    # ) in result.items():  # find all villain actions and put action in to a list
    #     data["villain_actions"] = [
    #         act["action"] for act in data["actions"] if act["actor"] == "Villain"
    #     ]

    return result


def stete_to_actions(state):
    """Get list of legal actions for current player.
    Returns:
        List of action names: ['fold', 'check', 'call', 'bet', 'raise']
            CompletionBettingOrRaisingTo  check_or_call
    Example:
        >>> game = PokerGame()
        >>> game.new_hand()
        >>> actions = game.legal_actions()
        >>> 'fold' in actions
        True
    """
    actions = []

    # Check if can fold
    if state.can_fold():
        actions.append("fold")

    # Check if can check/call
    if state.can_check_or_call():
        if state.checking_or_calling_amount == 0:
            actions.append("check")
        else:
            actions.append("call")

    # Check if can bet/raise
    if state.can_post_bring_in() or state.can_complete_bet_or_raise_to():
        # Get min/max bet amounts
        min_bet = state.min_completion_betting_or_raising_to_amount
        max_bet = state.max_completion_betting_or_raising_to_amount

        if min_bet is not None and max_bet is not None and min_bet <= max_bet:
            if state.completion_betting_or_raising_count == 0:
                # First action is a bet
                actions.append("bet")
            else:
                actions.append("raise")

    return actions
