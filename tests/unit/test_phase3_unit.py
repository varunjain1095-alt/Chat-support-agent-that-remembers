import os
import pathlib

def test_p3_03_no_raw_sdk_outside_memory():
    """P3-03 [UNIT] — No raw SDK calls outside memory.py"""
    src_dir = pathlib.Path(__file__).parent.parent.parent / "src"
    
    forbidden = ["mem0ai", "zep_cloud", "MemoryClient", "from zep"]
    
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.endswith(".py") and file != "memory.py":
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for term in forbidden:
                        assert term not in content, f"Forbidden term '{term}' found in {file}"
