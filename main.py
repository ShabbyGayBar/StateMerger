from state_merger import StateMerger
import os
import json

this_dir = os.path.dirname(__file__)
game_root_dir = "C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game"+'/'
merge_file = f'{this_dir}/merge_states.json'

def main():
    # Read merge state plan
    with open(merge_file, 'r', encoding='utf-8') as file:
        merge_dict = json.load(file)

    # Merge states
    state_merger = StateMerger(game_root_dir, f'{this_dir}/mod/', merge_dict, f'{this_dir}/data/')
    state_merger.merge_state_data(ignoreSmallStates=True)
    state_merger.merge_misc_data()
    state_merger.merge_loc_data()

    print("**Don't forget to manually add the 'if dlc' buildings to file**")

if __name__ == "__main__":
    main()
