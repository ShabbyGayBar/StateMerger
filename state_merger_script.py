from state_merger import StateMerger
import json

game_root_dir = "C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game"+'/'
merge_file = 'StateMerger/merge_states.json'
# Read merge state plan
with open(merge_file, 'r', encoding='utf-8') as file:
    merge_dict = json.load(file)

# Merge states
state_merger = StateMerger(game_root_dir, merge_dict)
state_merger.merge_state_data()
state_merger.merge_misc_data()

print("**Don't forget to manually add the 'if dlc' buildings to file**")
