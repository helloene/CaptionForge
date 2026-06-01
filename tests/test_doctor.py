from captionforge.cli import build_parser


def test_doctor_command_parses():
    args = build_parser().parse_args(["doctor"])
    assert args.command == "doctor"


def test_template_list_command_parses():
    args = build_parser().parse_args(["template", "list"])
    assert args.command == "template"
    assert args.template_command == "list"


def test_font_search_command_parses():
    args = build_parser().parse_args(["font", "search", "arial"])
    assert args.command == "font"
    assert args.font_command == "search"
