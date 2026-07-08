"""运行所有单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tests_passed = 0
tests_failed = 0

test_modules = [
    "tests.test_models",
    "tests.test_config",
    "tests.test_collector",
    "tests.test_html_writer",
    "tests.test_ai_analyzer",
    "tests.test_main",
    "tests.test_trending_fetcher",
]

for mod_name in test_modules:
    try:
        __import__(mod_name)
        mod = sys.modules[mod_name]
        test_fns = [fn for fn in dir(mod) if fn.startswith("test_")]
        for fn_name in test_fns:
            try:
                getattr(mod, fn_name)()
                tests_passed += 1
            except Exception as e:
                tests_failed += 1
                print(f"FAIL  {mod_name}.{fn_name}: {e}")
    except Exception as e:
        tests_failed += 1
        print(f"FAIL  import {mod_name}: {e}")

print(f"\n{'='*40}")
print(f"  Total: {tests_passed + tests_failed}  Passed: {tests_passed}  Failed: {tests_failed}")
print(f"{'='*40}")
sys.exit(0 if tests_failed == 0 else 1)
