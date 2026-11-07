"""Native parser boundary. Parent discards raw stdout/stderr and checks exit code."""
import json
from pathlib import Path
import sys
from .parser import parse_demo
from .aim import AnalysisError
from .config import private_file


def main():
    path,output,demo_id,sha256 = sys.argv[1:]
    try:
        report=parse_demo(Path(path),demo_id,sha256)
        payload={'report':report}
        code=0
    except AnalysisError as exc:
        payload={'error_code':str(exc)}
        code=1
    private_file(Path(output))
    Path(output).write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
