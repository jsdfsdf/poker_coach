import json
from collections import defaultdict
from typing import List, Dict, Any, Optional, Literal


def filter_dict_keys(original_dict: dict, keys_to_keep: list) -> dict:
    """
    Creates a new dictionary containing only the keys specified in keys_to_keep.
    Keys that are in keys_to_keep but not in original_dict are skipped.
    """
    return {key: original_dict[key] for key in keys_to_keep if key in original_dict}


def remove_commentary(original_string):
    # 1. Find the starting and ending indices
    start = original_string.find("commentary=")
    end = original_string.find(",", start)

    # 2. Reconstruct the string without the segment
    # Take everything before 'commentary=' (original_string[:start])
    # AND everything after the comma (original_string[end + 1:])
    efficient_string = original_string[:start] + original_string[end + 1 :].strip()
    return efficient_string


def action_from_state(state):
    actions = []
    allowed_types = (
        Folding,
        CheckingOrCalling,
        CompletionBettingOrRaisingTo,
        BoardDealing,
        BlindOrStraddlePosting,
    )
    for operation in state.operations:
        if isinstance(operation, allowed_types):
            actions.append(remove_commentary(str(operation)))
    return actions


def get_top_level_action(hand_dict):
    log_entry = {}
    streets = ["preflop", "flop", "turn", "river"]
    for street in streets:
        # log_entry[f"villain_action_{street}"] = "" # dont keep all
        if hand_dict["streets_history"].get(street):
            log_entry[f"villain_action_{street}"] = [
                act["action"]
                for act in hand_dict["streets_history"][street]["actions"]
                if act["actor"] == "Villain"
            ]
            # hand_dict["streets_history"][
            #     street
            # ]["villain_actions"]
    return log_entry
