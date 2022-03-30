import re
import argparse
import os
import sys
import ast
from collections import defaultdict


class StaticCodeAnalyzer:
    def __init__(self, path, code):
        self.code = code
        self.path = path
        self.issues = []
        self.node_errors = defaultdict(list)
        self.node_methods()
        self.line_methods()

    def node_methods(self):
        tree = ast.parse(self.code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                camel_case_template = re.compile("([A-Z][a-z]*)+$")
                if not camel_case_template.match(class_name):
                    self.node_errors[node.lineno].append(["S008", class_name])
            elif isinstance(node, ast.FunctionDef):
                function_name = node.name
                if StaticCodeAnalyzer.is_not_snake_case(function_name):
                    self.node_errors[node.lineno].append(["S009", function_name])
                argument_names = [argument.arg for argument in node.args.args]
                for name in argument_names:
                    if StaticCodeAnalyzer.is_not_snake_case(name):
                        self.node_errors[node.lineno].append(["S010", name])
                for default in node.args.defaults:
                    if not isinstance(default, ast.Constant):
                        self.node_errors[node.lineno].append(["S012"])
                        break
                variables_in_function = set()
                for statement in ast.walk(node):
                    if isinstance(statement, ast.Assign):
                        variables = []
                        for target in statement.targets:
                            try:
                                variable_name = target.id
                            except AttributeError:
                                pass
                            else:
                                variables.append(variable_name)
                        for name in variables:
                            if name not in variables_in_function:
                                variables_in_function.add(name)
                                if StaticCodeAnalyzer.is_not_snake_case(name):
                                    self.node_errors[statement.lineno].append(
                                        ["S011", name]
                                    )

    def line_methods(self):
        lines = {i: line.rstrip() for i, line in enumerate(self.code.splitlines(), 1)}
        blank_line_counter = 0
        for line_number, line in lines.items():
            if line:
                line_errors = []
                for method in (StaticCodeAnalyzer.too_long,
                               StaticCodeAnalyzer.indentation,
                               StaticCodeAnalyzer.semicolon,
                               StaticCodeAnalyzer.space_before_inline_comment,
                               StaticCodeAnalyzer.todo_found,
                               StaticCodeAnalyzer.space_after_construction,
                               ):
                    found_error, *error = method(line)
                    if found_error:
                        line_errors.append(error)
                if blank_line_counter > 2:
                    line_errors.append(["S006"])
                blank_line_counter = 0
                for error in line_errors + self.node_errors[line_number]:
                    self.issues.append(Issue(self.path, line_number, error))
            else:
                blank_line_counter += 1

    @staticmethod
    def find_string(line):
        single_quote = re.search("'.*'", line)
        double_quote = re.search('".*"', line)
        return single_quote or double_quote

    @staticmethod
    def find_comment(line):
        comment = line.find('#')
        while comment > -1:
            string = StaticCodeAnalyzer.find_string(line)
            if not string:
                return comment
            if comment < string.start() or string.end() < comment:
                return comment
            comment = line[comment + 1:].find('#')
        return comment

    @staticmethod
    def remove_comment(line):
        comment_start = StaticCodeAnalyzer.find_comment(line)
        if comment_start < 0:
            return line.rstrip()
        return line[:comment_start].rstrip()

    @staticmethod
    def too_long(line):
        if len(line) >= 80:
            return True, "S001"
        return False,

    @staticmethod
    def indentation(line):
        count = 0
        while line[count] == " ":
            count += 1
        if count % 4:
            return True, "S002"
        return False,

    @staticmethod
    def semicolon(line):
        code = StaticCodeAnalyzer.remove_comment(line)
        if code.endswith(";"):
            return True, "S003"
        return False,

    @staticmethod
    def space_before_inline_comment(line):
        comment = StaticCodeAnalyzer.find_comment(line)
        if comment > 1:
            if line[comment - 2: comment] != "  ":
                return True, "S004"
        return False,

    @staticmethod
    def todo_found(line):
        if '#' in line:
            comment_index = line.index('#')
            if "todo" in line[comment_index:].lower():
                return True, "S005"
        return False,

    @staticmethod
    def space_after_construction(line):
        construction_name = re.compile(" *(def|class) ")
        construction_found = construction_name.match(line)
        if construction_found:
            try:
                character_after = line[construction_found.end()]
            except IndexError:
                pass
            else:
                if character_after == " ":
                    return True, "S007", construction_found.group(1)
        return False,

    @staticmethod
    def is_not_snake_case(name):
        snake_case_template = re.compile("^_{0,2}[a-z][a-z0-9]*(_[a-z0-9]+)*(__)?$")
        return not snake_case_template.search(name)


class Issue:
    error_codes = {"S001": "Too long",
                   "S002": "Indentation is not a multiple of four",
                   "S003": "Unnecessary semicolon",
                   "S004": "At least two spaces required before inline comments",
                   "S005": "TODO found",
                   "S006": "More than two blank lines used before this line",
                   "S007": "Too many spaces after '{}'",
                   "S008": "Class name '{}' should be written in CamelCase",
                   "S009": "Function name '{}' should be written in snake_case",
                   "S010": "Argument name '{}' should be snake_case",
                   "S011": "Variable '{}' in function should be snake_case",
                   "S012": "Default argument value is mutable",
                   }

    def __init__(self, path_to_file, line_number, message):
        self.path_to_file = path_to_file
        self.line_number = line_number
        self.error_code = message[0]
        self.construction_name = message[1:]
        self.error_message = self.error_codes[self.error_code].format(*self.construction_name)

    def __repr__(self):
        return f"{self.path_to_file}: Line {self.line_number}: {self.error_code} {self.error_message}"


def get_filenames():
    parser = argparse.ArgumentParser(
        description="This program statically analyzes python code in a single "
                    "file or in multiple files in a single directory given as "
                    "a command line argument."
    )
    parser.add_argument("file_or_directory",
                        help="Enter the name of the python file or the "
                             "directory in which the python code file or files"
                             " are to be found."
                        )
    f_or_d = parser.parse_args().file_or_directory
    if not os.access(f_or_d, os.F_OK):
        sys.stderr.write(f'{f_or_d} does not exist.\n')
        sys.exit()
    elif os.path.isdir(f_or_d):
        f_and_d = sorted(os.listdir(f_or_d))
        return [os.path.join(f_or_d, f) for f in f_and_d if f.endswith(".py")]
    elif os.path.isfile(f_or_d):
        if f_or_d.endswith(".py"):
            return [f_or_d]
        else:
            sys.stderr.write(
                f'{f_or_d} does not end with ".py"\n'
            )
            sys.exit()


def main():
    issues = []
    for filename in get_filenames():
        with open(filename, "r", encoding="utf-8") as source:
            source_code = source.read()
        sca = StaticCodeAnalyzer(filename, source_code)
        issues.extend(sca.issues)
    for issue in issues:
        print(issue)


if __name__ == '__main__':
    main()
