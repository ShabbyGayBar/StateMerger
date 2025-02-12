import re
import codecs
import json


INDENT_SIZE = 4
conditional_tokens = ["=", "<", ">", "<=", ">="]


class ParadoxFileParser:
    def __init__(self):
        self.data = {}

    def tokenize(self, text):
        token_pattern = r'\{|\}|\s*[><=]+\s*|"[^"]*"|[\w\-\.:]+'
        text = "\n".join(
            [
                line.split("#")[0]
                for line in text.split("\n")
                if not line.startswith("#")
            ]
        )
        tokens = re.findall(token_pattern, text.strip())
        return [t.strip() for t in tokens]

    def calculate_depths(self, tokens):
        """
        Calculates and assigns a depth level to each token.
        Depth increments inside each '{' and decrements upon each '}'.
        """
        depths = []
        current_depth = 0

        for token in tokens:
            if token == "}":
                current_depth -= 1
            depths.append(current_depth)
            if token == "{":
                current_depth += 1

        return depths

    def extract_tokens_within_braces(self, tokens):
        extracted_tokens = []
        extraction_started = False
        depths = self.calculate_depths(tokens)
        for token, depth in zip(tokens, depths):
            if depth == 0 and token == "{":
                extraction_started = True
                continue
            if extraction_started:
                if depth == 0 and token == "}":
                    break
                extracted_tokens.append(token)

        return extracted_tokens

    def is_value_simple(self, tokens):
        return tokens[0] != "{"

    def is_value_dictionary(self, tokens):
        value_tokens = self.extract_tokens_within_braces(tokens)
        return any([t in conditional_tokens for t in value_tokens])

    def next_token(self, tokens):
        if len(tokens) == 0:
            return None, []
        else:
            return tokens[0], tokens[1:]

    def parse_value(self, tokens):
        if self.is_value_simple(tokens):
            return self.parse_simple_value(tokens)
        elif self.is_value_dictionary(tokens):
            return self.parse_object(tokens)
        else:
            list_tokens = self.extract_tokens_within_braces(tokens)
            return self.parse_list(list_tokens), tokens[len(list_tokens) + 2 :]

    def parse_list(self, tokens):
        return tokens

    def parse_simple_value(self, tokens):
        return tokens[0], tokens[1:]

    def parse_object(self, tokens):
        first_token, tokens = self.next_token(tokens)
        if first_token != "{":
            raise ValueError(
                f"Expected '{first_token}' to be '{{' when parsing object, got '{first_token}'"
            )
        obj = {}
        while True:
            token, tokens = self.next_token(tokens)
            if token is None or token == "}":
                return obj, tokens
            else:
                key = token
                symbol, tokens = self.next_token(tokens)
                if (
                    symbol not in conditional_tokens
                ):  # Extend this list to support more symbols
                    raise ValueError(
                        f"Expected a valid symbol after key in object, got: '{symbol}' after '{key}'"
                    )
                value, tokens = self.parse_value(tokens)
                if key in obj.keys() and obj[key] != (symbol, value):
                    obj[key] += (symbol, value)
                else:
                    obj[key] = (symbol, value)

    def parse_file(self, file_path):
        # Update self.data with the parsed content
        with codecs.open(file_path, "r", "utf-8-sig") as f:
            text = f.read()
        tokens = self.tokenize("{" + text + "}")
        self.merge_data(self.parse_object(tokens)[0])

    def merge_data(self, new_data):
        idleElements = [None, "", [], {}, '=', '\"=\"']
        def remove_idle_element(dic):
            if isinstance(dic, tuple):
                dic = remove_idle_element(list(dic))
            if isinstance(dic, list):
                for i in range(len(dic) - 1, -1, -1):
                    if dic[i] in idleElements:
                        dic.pop(i)
                    else:
                        dic[i] = remove_idle_element(dic[i])
                if len(dic) == 1:
                    return dic[0]
                # if there is list under list, decompose it
                for i in range(len(dic) - 1, -1, -1):
                    if isinstance(dic[i], list):
                        dic = dic[:i] + dic[i] + dic[i + 1:]
                return dic
            elif isinstance(dic, dict):
                for key, value in dic.items():
                    dic[key] = remove_idle_element(value)
                return dic
            return dic
        new_data = remove_idle_element(new_data)  # Recursively remove idle elements ('=') from data
        for key in new_data.keys():
            if new_data[key] in idleElements:
                continue
            if key not in self.data:
                self.data[key] = new_data[key]
                continue
            if isinstance(self.data[key], dict) and isinstance(new_data[key], dict):
                self.data[key].update(new_data[key])
                continue
            if isinstance(self.data[key], tuple):
                self.data[key] = list(self.data[key])
            elif not isinstance(self.data[key], list):
                self.data[key] = [self.data[key]]
            if isinstance(new_data[key], list):
                self.data[key] += new_data[key]
            elif isinstance(new_data[key], tuple):
                self.data[key] += list(new_data[key])
            else:
                self.data[key].append(new_data[key])

    def detect_modifications(self, base_parser):
        return self._compare_dicts(self.data, base_parser.data)

    def _compare_dicts(self, mod_dict, base_dict):
        changes = {}
        for key, mod_value in mod_dict.items():
            if key not in base_dict:
                changes[key] = {"change_type": "added", "change_value": mod_value}
            elif mod_value != base_dict[key]:
                if isinstance(mod_value, tuple) and isinstance(base_dict[key], tuple):
                    if isinstance(mod_value[1], dict) and isinstance(
                        base_dict[key][1], dict
                    ):
                        changes_in_nested_dict = self._compare_dicts(
                            mod_value[1], base_dict[key][1]
                        )
                        if changes_in_nested_dict:
                            changes[key] = {
                                "change_type": "modified",
                                "change_value": (mod_value[0], changes_in_nested_dict),
                            }
                    elif isinstance(mod_value[1], list) and isinstance(
                        base_dict[key][1], list
                    ):
                        changes_in_list = self._compare_lists(
                            mod_value[1], base_dict[key][1]
                        )
                        if changes_in_list:
                            changes[key] = {
                                "change_type": "modified",
                                "change_value": (mod_value[0], changes_in_list),
                            }
                    else:
                        changes[key] = {
                            "change_type": "modified",
                            "change_value": mod_value,
                        }
                else:
                    changes[key] = {
                        "change_type": "modified",
                        "change_value": mod_value,
                    }

        for key in base_dict:
            if key not in mod_dict:
                changes[key] = {
                    "change_type": "removed",
                    "change_value": base_dict[key],
                }

        return changes

    def _compare_lists(self, mod_list, base_list):
        list_changes = []
        base_set = set(base_list)
        mod_set = set(mod_list)

        added_items = mod_set - base_set
        removed_items = base_set - mod_set

        for item in added_items:
            list_changes.append(("added", item))

        for item in removed_items:
            list_changes.append(("removed", item))

        return list_changes if list_changes else None

    def save_changes_to_json(self, base_parser, file_path):
        changes = self.detect_modifications(base_parser)
        with open(file_path, "w") as json_file:
            json.dump(changes, json_file, indent=4)

    def set_data_from_changes_json(self, base_parser, changes_file_path):
        with open(changes_file_path, "r") as json_file:
            changes = json.load(json_file)
        data = base_parser.data.copy()
        self.data = self._apply_changes(data, changes)

    def _apply_changes(self, data, changes):
        for key, value in changes.items():
            change_type, change_value = value["change_type"], value["change_value"]
            if change_type == "added":
                operator, right_value = change_value[0], change_value[1]
                data[key] = (operator, self._format_to_tuples(right_value))
            elif change_type == "removed" and key in data:
                del data[key]
            elif change_type == "modified":
                operator, right_value = change_value[0], change_value[1]
                _, original_value = data[key]
                if isinstance(right_value, dict) and isinstance(original_value, dict):
                    data[key] = (
                        operator,
                        self._apply_changes(original_value, right_value),
                    )
                elif isinstance(right_value, list) and isinstance(original_value, list):
                    data[key] = (
                        operator,
                        self._merge_lists(original_value, right_value),
                    )
                else:
                    data[key] = (operator, self._format_to_tuples(right_value))

        return data

    def _format_to_tuples(self, change_value):
        if isinstance(change_value, dict):
            for key, value in change_value.items():
                operator, right_value = value[0], value[1]
                change_value[key] = (operator, self._format_to_tuples(right_value))
        elif isinstance(change_value, list):
            return tuple(change_value)
        else:
            return change_value

    def _merge_lists(self, base_list, changes):
        for change_type, item in changes:
            if change_type == "added":
                base_list.append(item)
            elif change_type == "removed":
                base_list.remove(item)
        return base_list

    def __repr__(self):
        return self.format_dict_to_string(self.data)

    def format_dict_to_string(self, d, indent=0):
        # Convert self.data into the game's file format and write to file_path
        lines = []
        for key, value in d.items() if isinstance(d, dict) else enumerate(d):
            done = False
            while not done:
                # For lists, the key is the index and is not used in formatting
                line_prefix = " " * indent

                if type(value) == tuple:
                    symbol, actual_value = value[0], value[1]
                    formatted_value = f"{symbol} {actual_value}"
                    value = value[2:]
                    if len(value) == 0:
                        done = True
                else:
                    actual_value = value
                    formatted_value = f"{actual_value}"
                    done = True

                # For dictionaries, include the key in the line
                if isinstance(d, dict):
                    line = f"{line_prefix}{key} {formatted_value}"
                else:  # For lists, just format the value
                    line = f"{line_prefix}{formatted_value}"

                if isinstance(actual_value, dict) or isinstance(actual_value, list):
                    lines.append(f"{line_prefix}{key} {symbol} {{")
                    lines.append(
                        self.format_dict_to_string(actual_value, indent + INDENT_SIZE)
                    )
                    lines.append(" " * indent + "}")
                else:
                    lines.append(line)

        return "\n".join(lines)

    def write_file(self, file_path, base_parser):
        modified_data = self._get_modified_data(self.data, base_parser)
        formatted_data = self.format_dict_to_string(modified_data)
        with open(file_path, "w") as file:
            file.write(formatted_data)

    def _get_modified_data(self, mod_data, base_parser):
        changes = self.detect_modifications(base_parser)
        modified_data = {}
        for key in changes:
            modified_data[key] = mod_data[key]
        return modified_data


# Example usage
# parser = ParadoxFileParser()
# parser.parse_file(
#    "F:\Libraries\Documents\Paradox Interactive\Victoria 3\mod\Production Methods\common\production_methods\extra_pms.txt"
# )

# print(parser.format_dict_to_string(parser.data))
