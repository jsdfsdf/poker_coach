"""
Streamlit UI for Poker Coach trainer.

Two-column layout:
- Left: Action panel (Fold/Check/Call/Bet/Raise with slider)
- Right: Hand timeline showing actions, pot, stacks, board

Features:
- Play full hands against simple AI opponent
- Reveal hole cards after hand completion
- Get coaching notes via API call
- Automatic logging to JSONL
"""

import streamlit as st
import yaml
from typing import Optional
from datetime import datetime
from engine.game import PokerGame
from data.db_manager import HANDS_COLLECTION
from llm.llm_helper import get_top_level_action, filter_dict_keys
import re
import logging

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_config():
    """Load configuration from config.yaml."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


def init_session_state():
    """Initialize Streamlit session state."""
    if "game" not in st.session_state:
        st.session_state.game = PokerGame()
        st.session_state.game.new_hand()
        st.session_state.reveal = False
        st.session_state.coach_note = None
        st.session_state.hand_logged = False


def get_hand_to_log(game):
    hand_dict = game.get_state_dict(hero_index=1 - game.hero_index, reveal=False)
    hand_dict["start_effective_stack"] = min(game.state.starting_stacks)
    to_keep = [
        "hero_pos",
        "board",
        "streets_history",
        "start_effective_stack",
        "big_blind",
    ]
    hand_dict = filter_dict_keys(hand_dict, to_keep)
    hand_dict["villain_hand"] = (
        game.hero_cards
    )  # record human hand for ai it is villain
    return hand_dict


def log_hand(hand_dict: dict, coach_note: Optional[str] = None):
    """Append completed hand to data/hands.jsonl.

    Args:
        hand_dict: Complete hand state dictionary
        coach_note: Optional coaching note to include
    """

    log_entry = {
        "timestamp": datetime.now(),
        # "config": {
        #     "small_blind": st.session_state.game.small_blind,
        #     "big_blind": st.session_state.game.big_blind,
        #     "starting_stack": st.session_state.game.starting_stack,
        # },
        "hand": hand_dict,
        "coach_note": coach_note,
    }
    top_level = get_top_level_action(hand_dict)
    if len(hand_dict["streets_history"]["preflop"]["actions"]) == 1:
        return  # dont store hands when ai folds
    log_entry = {**log_entry, **top_level}

    try:
        result = HANDS_COLLECTION.insert_one(log_entry)
        print(f"➡️ Hand logged successfully with ID: {result.inserted_id}")
    except Exception as e:
        print(f"⚠️ Error inserting document: {e}")


# --- helper to render cards like "9c 8s" -> "9♣ 8♠" ---
def _format_cards(cards):
    if not cards:
        return "–"

    if isinstance(cards, str):
        # tokens = cards.split()
        tokens = re.split(r"[,\s]+", cards)
    else:
        tokens = cards

    suit_map = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
    pretty = []
    for c in tokens:
        c = str(c)
        if len(c) >= 2:
            rank = c[0]
            suit_char = c[1].lower()
            suit = suit_map.get(suit_char, suit_char)
            pretty.append(f"{rank}{suit}")
        else:
            pretty.append(c)
    return " ".join(pretty)


# --- helpers to render cards like "9c 8s" -> nice HTML tiles ---
def _format_cards_html(cards):
    if not cards:
        return "–"

    if isinstance(cards, str):
        tokens = re.split(r"[,\s]+", cards)
    else:
        tokens = cards

    suit_symbol_map = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
    suit_name_map = {"s": "spade", "h": "heart", "d": "diamond", "c": "club"}

    html_cards = []
    for c in tokens:
        c = str(c)
        if len(c) >= 2:
            rank = c[0]
            suit_code = c[1].lower()
            suit_symbol = suit_symbol_map.get(suit_code, "?")
            suit_name = suit_name_map.get(suit_code, "")

            # color logic
            if suit_code in ("h", "d"):
                suit_color_class = "suit-red"
                extra_class = ""
            else:
                suit_color_class = "suit-black"
                extra_class = "suit-spade" if suit_code == "s" else "suit-club"

            # apply the tint using suit name on parent
            html_cards.append(
                f"""
                <span class="poker-card {suit_name}">
                    <span class="rank">{rank}</span>
                    <span class="suit {suit_color_class} {extra_class}">{suit_symbol}</span>
                </span>
                """
            )
        else:
            html_cards.append(
                f'<span class="poker-card"><span class="rank">{c}</span></span>'
            )

    return " ".join(html_cards)


def _inject_card_css():
    st.markdown(
        """
        <style>
        .poker-card {
            display: inline-flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            width: 2.6rem;
            height: 3.6rem;
            padding: 0.25rem;
            margin-right: 0.35rem;
            border-radius: 8px;
            border: 1px solid #dde1e7;
            background: #ffffff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.10);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            transition: background-color 0.15s ease-in-out;  /* smooth fade */
        }

        /* Text styling */
        .poker-card .rank {
            font-weight: 700;
            font-size: 1.2rem;
        }
        .poker-card .suit {
            font-size: 1.3rem;
        }

        /* Base color groups */
        .suit-red { color: #d62828; }
        .suit-black { color: #111111; }

        /* Suit-specific tinting (light pastel background) */
        .poker-card.heart,
        .poker-card.diamond {
            background: #ffe5e5;    /* soft red/pink */
        }
        .poker-card.spade {
            background: #e8e8ff;    /* very light blue */
        }
        .poker-card.club {
            background: #e7ffed;    /* soft green */
        }

        /* Extra clarity (optional suited boldness) */
        .suit-spade { text-shadow: 0 0 2px rgba(0,0,0,0.3); }
        .suit-club { color: #036666; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_timeline():
    """Render hand timeline in right column."""
    _inject_card_css()

    game = st.session_state.game
    state = game.get_state_dict(
        hero_index=game.hero_index,
        reveal=st.session_state.reveal,
        add_reason=st.session_state.reveal,
    )

    st.subheader("Hand Timeline")

    # === TOP SUMMARY: Hero / Villain / Hand State ===
    # Define colors for easy maintenance
    HERO_COLOR = "#4CAF50"  # Green for Hero
    VILLAIN_COLOR = "#E57373"  # Light Red/Salmon for Villain
    POT_COLOR = "#FFC107"  # Amber for Pot
    LABEL_COLOR = "#808080"  # Gray for labels

    # 1. Use st.container() for visual grouping (optional, but good practice)
    with st.container():
        # 2. Use columns with adjusted widths (kept your original ratio)
        col_hero, col_state, col_villain = st.columns([1, 1, 1.1])

        # --- HERO COLUMN ---
        with col_hero:
            st.markdown("##### Hero")

            # Position: Bold and Hero Color
            st.markdown(
                f"<div style='color:{LABEL_COLOR};'>Pos: <span style='color:{HERO_COLOR}; font-weight:bold;'>{state['hero_pos']}</span></div>",
                unsafe_allow_html=True,
            )

            # Stack: Bold and Hero Color
            st.markdown(
                f"<div style='color:{LABEL_COLOR};'>Stack: <span style='color:{HERO_COLOR}; font-size:1.1em; font-weight:bold;'>{state['hero_stack']}</span></div>",
                unsafe_allow_html=True,
            )

            st.markdown("**Cards:**")
            st.markdown(_format_cards_html(state["hero_hand"]), unsafe_allow_html=True)

        # --- HAND STATE COLUMN ---
        with col_state:
            st.markdown("##### Hand State")

            # Street: Bold
            st.markdown(
                f"<div style='color:{LABEL_COLOR};'>Street: <span style='font-weight:bold;'>{state['current_street'].capitalize()}</span></div>",
                unsafe_allow_html=True,
            )

            # Pot: Bold and Pot Color
            st.markdown(
                f"<div style='color:{LABEL_COLOR};'>Pot: <span style='color:{POT_COLOR}; font-weight:bold;'>{state['total_pot_now']}</span></div>",
                unsafe_allow_html=True,
            )

            st.markdown("**Board:**")
            if state["board"]:
                st.markdown(_format_cards_html(state["board"]), unsafe_allow_html=True)
            else:
                st.markdown("–")

        # --- VILLAIN COLUMN ---
        with col_villain:
            st.markdown("##### Villain")

            # Add a placeholder for position/label symmetry if villain pos isn't tracked
            st.markdown(
                f"<div style='height: 19px;'></div>", unsafe_allow_html=True
            )  # Matches the height of the 'Pos' line in the Hero column

            # Stack: Bold and Villain Color
            st.markdown(
                f"<div style='color:{LABEL_COLOR};'>Stack: <span style='color:{VILLAIN_COLOR}; font-size:1.1em; font-weight:bold;'>{state['villain_stack']}</span></div>",
                unsafe_allow_html=True,
            )

            # Placeholder for symmetry with the Cards label
            st.markdown(f"<div style='height: 19px;'></div>", unsafe_allow_html=True)
            st.markdown(
                f"<div style='height: 28px;'></div>", unsafe_allow_html=True
            )  # Matches the height of the card display area

        # === SHOWDOWN CARDS (OPTIONAL) ===
        if st.session_state.reveal and "hole_cards" in state:
            st.markdown("---")
            st.markdown("##### Showdown Cards")

            hero_cards_html = _format_cards_html(state["hole_cards"]["hero"])
            villain_cards_html = _format_cards_html(state["hole_cards"]["villain"])

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Hero:**")
                st.markdown(hero_cards_html, unsafe_allow_html=True)
            with c2:
                st.markdown("**Villain:**")
                st.markdown(villain_cards_html, unsafe_allow_html=True)

    st.write("---")
    st.markdown("### ⏱️ Action Timeline")  # Use markdown heading for better styling

    if state["streets_history"]:
        for street, street_data in state["streets_history"].items():
            # Capitalize the street name and bold it
            st.markdown(f"#### **{street.capitalize()}**")

            # 2. Iterate through each action within that street
            for i, action_detail in enumerate(street_data["actions"]):

                # 1. Define colors for Hero and Villain
                actor = action_detail["actor"]

                # Use distinct colors for players
                if actor.lower() == "hero":
                    player_style = "color:#1E90FF;"  # Dodger Blue for Hero
                elif actor.lower() == "villain":
                    player_style = "color:#DC143C;"  # Crimson Red for Villain
                else:
                    player_style = "color:black;"

                # 2. Format the action amount (optional green color)
                amt_text = action_detail["amt"] or ""
                if amt_text != "":
                    amt_text = f" <span style='color:green;'>**{amt_text}**</span>"

                # 3. Combine the components into a formatted label using HTML
                html_label = f"{i+1}. <span style='{player_style}'>**{actor}**</span> **{action_detail['action']}**{amt_text}".strip()
                amt_raw = action_detail["amt"] or ""
                simple_label = f"**{i+1}.** **{actor}** **{action_detail['action']}** {amt_raw}".strip()
                if "llm_reason" in action_detail:
                    # If reasoning exists, use expander with the formatted label
                    with st.expander(simple_label, expanded=False):
                        st.markdown(action_detail["llm_reason"])
                else:
                    # If no reasoning, display the formatted label directly
                    st.markdown(html_label, unsafe_allow_html=True)
    else:
        st.text("No actions yet")


def render_coach_note(note: dict):
    if not note:
        return

    with st.container(border=True):
        st.markdown("### 🧠 Coach’s Analysis")

        # Intent (what you tried to do)
        if "intent" in note:
            st.markdown("**Intent**")
            st.write(note["intent"])

        # Biggest leak (make it pop as a "problem")
        if "biggest_leak" in note:
            st.markdown("**Biggest Leak**")
            st.error(note["biggest_leak"])

        # Range / stack awareness
        if "range_size_awareness" in note:
            st.markdown("**Range & Size Awareness**")
            st.warning(note["range_size_awareness"])

        # Better lines – turn into a small list
        if "better_lines" in note:
            st.markdown("**Better Lines Next Time**")
            # If it’s already a list, great; if it’s a long string, just show it
            if isinstance(note["better_lines"], list):
                for i, line in enumerate(note["better_lines"], start=1):
                    st.markdown(f"- **Line {i}.** {line}")
            else:
                st.success(note["better_lines"])

        # Question / drill – small and subtle
        if "question" in note:
            st.markdown("**Reflective Question**")
            st.info(note["question"])


def show_winner(game):
    payoffs = game.state.payoffs
    hero = game.hero_index
    hero_payoff = payoffs[hero]

    if hero_payoff > 0:
        st.success(f"💰 Hero wins {hero_payoff} chips!")
    elif hero_payoff < 0:
        st.error(f"😞 Villain wins {-hero_payoff} chips.")
    else:
        st.info("🤝 It's a tie (no chips exchanged).")


def render_action_panel():
    """Render action panel in left column."""
    game = st.session_state.game

    st.subheader("Action Panel")

    # Check if hand is complete
    if game.is_terminal():

        # winner
        show_winner(game)

        col1, col2, col3 = st.columns(3)

        with col1:
            # Reveal toggle
            reveal_on = st.toggle("Reveal Hole Cards", value=st.session_state.reveal)
            if reveal_on != st.session_state.reveal:
                st.session_state.reveal = reveal_on
                st.rerun()

        # New hand button
        with col2:
            if st.button("Start New Hand", type="primary"):
                # Log hand if not already logged
                if not st.session_state.hand_logged:
                    hand_dict = get_hand_to_log(game)
                    log_hand(hand_dict, st.session_state.coach_note)

                # Reset game
                # st.session_state.game = PokerGame()
                if (
                    min(st.session_state.game.state.stacks) < game.big_blind
                ):  # if stacks not enoug hfor big blind
                    st.session_state.game = PokerGame()
                st.session_state.game.new_hand()
                st.session_state.reveal = False
                st.session_state.coach_note = None
                st.session_state.hand_logged = False
                st.rerun()

        # new chips
        with col3:
            if st.button(
                "Start New Game",
            ):
                st.session_state.game = PokerGame()
                st.session_state.game.new_hand()
                st.session_state.reveal = False
                st.session_state.coach_note = None
                st.session_state.hand_logged = False
                st.rerun()

        # Get coach note button
        if st.session_state.reveal:
            if st.button("Get Coach Note", type="primary"):
                with st.spinner("Analyzing hand..."):
                    hand_dict = get_hand_to_log(game)
                    coach_note = game.get_coach_note()
                    st.session_state.coach_note = coach_note

                    # Log hand with coach note
                    if not st.session_state.hand_logged:
                        log_hand(hand_dict, coach_note)
                        st.session_state.hand_logged = True

                    st.rerun()

        # Show coach note if available
        if st.session_state.coach_note:
            st.write("---")
            render_coach_note(st.session_state.coach_note)

        return

    # Check whose turn it is
    current_player = game.get_current_player()

    if current_player == "villain":
        st.info("Villain is thinking...")

        # Auto-play villain action
        game.villian_llm_action()
        # game.villain_action()
        # print("run finish")
        st.rerun()
        return

    # Hero's turn - show action buttons
    st.write("**Your Turn**")

    legal = game.legal_actions()

    if not legal:
        st.warning("No legal actions available")
        return

    # Action buttons
    col1, col2 = st.columns(2)

    with col1:
        if "fold" in legal:
            if st.button("Fold", use_container_width=True):
                game.apply_action("fold")
                st.rerun()

        if "check" in legal:
            if st.button("Check", use_container_width=True):
                game.apply_action("check")
                st.rerun()

    with col2:
        if "call" in legal:
            call_amt = game.state.checking_or_calling_amount if game.state else 0
            if st.button(f"Call {call_amt}", use_container_width=True):
                game.apply_action("call")
                st.rerun()

    # Bet/Raise with slider
    if "bet" in legal or "raise" in legal:
        st.write("---")
        action_type = "bet" if "bet" in legal else "raise"
        min_amt, max_amt = game.get_bet_range()

        if min_amt is not None and max_amt is not None and min_amt <= max_amt:
            if min_amt < max_amt:
                bet_amount = st.slider(
                    f"{action_type.capitalize()} Amount",
                    min_value=int(min_amt),
                    max_value=int(max_amt),
                    value=int(min_amt),
                    step=max(1, int((max_amt - min_amt) / 20)),
                )
            else:
                bet_amount = min_amt

            if st.button(
                f"{action_type.capitalize()} {bet_amount}",
                type="primary",
                use_container_width=True,
            ):
                game.apply_action(action_type, bet_amount)
                st.rerun()


def main():
    """Main Streamlit app."""
    st.set_page_config(page_title="Poker Coach Trainer", page_icon="♠️", layout="wide")

    st.title("♠️ Poker Coach Trainer")
    st.write("Heads-up Texas Hold'em with AI coaching")

    # Initialize session state
    init_session_state()

    # Two-column layout
    left_col, right_col = st.columns([1, 1])

    with left_col:
        render_action_panel()

    with right_col:
        render_timeline()


if __name__ == "__main__":
    main()
