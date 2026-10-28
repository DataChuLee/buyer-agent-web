import ast
import json
import re
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = BACKEND_DIR / "Product_Search.ipynb"


def _code_cells():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    return [
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
    ]


def _cell_containing(text):
    for source in _code_cells():
        if text in source:
            return source
    raise AssertionError(f"Notebook code cell containing {text!r} not found")


class ProductSearchNotebookTest(unittest.TestCase):
    def test_lcel_parallel_tavily_cells_exist(self):
        code = "\n".join(_code_cells())

        self.assertIn("RunnableParallel", code)
        self.assertIn("RunnableLambda", code)
        self.assertIn("parallel_tavily", code)
        self.assertIn("seller_branch", code)
        self.assertIn("max_concurrency", code)

        for tool_name in [
            "tool_crazy",
            "tool_soccerboom",
            "tool_redsoccer",
            "tool_capo",
        ]:
            self.assertIn(tool_name, code)

    def test_rule_based_product_filter_cells_exist(self):
        code = "\n".join(_code_cells())

        expected_symbols = [
            "filter_tavily_candidates",
            "PRODUCT_SEARCH_DROP_URL_PARTS",
            "MIN_SCORE_THRESHOLD",
            "extract_product_items_from_candidate",
            "extract_product_items",
            "product_items",
            "raw_name",
            "sale_price",
            "BOOT_SURFACE_KEYWORDS",
            "NON_BOOT_KEYWORDS",
            "SERIES_PATTERNS",
            "extract_surface",
            "extract_series_name",
            "normalize_product_item",
            "_price_match_for_item",
            "collect_product_filter_diagnostics",
            "filter_normalized_products",
            "price_match_source",
            "rejection_summary",
            "rejected_products",
            "dedupe_extracted_series",
        ]

        for symbol in expected_symbols:
            self.assertIn(symbol, code)

        removed_symbols = [
            "ChatPromptTemplate",
            "ExtractedSeries",
            "ExtractedSeriesBatch",
            "series_extraction_chain",
            "series_extraction_result",
            "series_extraction_payload_json",
            "products_json",
            "with_structured_output",
            "abatch",
            "candidate_extraction_inputs",
            "extraction_batches",
            "build_series_extraction_input",
            "build_series_extraction_context",
            "series_extraction_context",
        ]
        for symbol in removed_symbols:
            self.assertNotIn(symbol, code)

    def test_product_item_extraction_pairs_name_and_sale_price(self):
        source = _cell_containing("def extract_product_items_from_candidate")
        parser_source = source.split("\n\nproduct_items = extract_product_items", 1)[0]
        namespace = {
            "re": re,
            "_compact_spaces": lambda value: re.sub(r"\s+", " ", str(value or "")).strip(),
            "_excerpt": lambda value, limit=320: str(value or "")[:limit],
        }
        exec(parser_source, namespace)

        product_name = "\uc0c1\ud488\uba85"
        maker = "\uc81c\uc870\uc0ac"
        consumer_price = "\uc18c\ube44\uc790\uac00"
        sale_price = "\ud310\ub9e4\uac00"
        won = "\uc6d0"
        candidate = {
            "seller": "\uc0ac\ucee4\ubd90",
            "seller_key": "soccerboom",
            "url": "https://soccerboom.co.kr/category/test",
            "title": "test category",
            "rank": 1,
            "score": 0.77,
            "content": (
                f"{product_name} : Tiempo Legend 10 Academy TF + "
                f"{maker} : Nike + {consumer_price} : 109,000{won} + "
                f"{sale_price} : 82,300{won} + "
                f"{product_name} : Mercurial Vapor 17 Academy TF + "
                f"{maker} : Nike + {consumer_price} : 109,000{won} + "
                f"{sale_price} : 80,700{won}"
            ),
        }

        items = namespace["extract_product_items"]([candidate])

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["raw_name"], "Tiempo Legend 10 Academy TF")
        self.assertEqual(items[0]["consumer_price"], 109000)
        self.assertEqual(items[0]["sale_price"], 82300)
        self.assertEqual(items[1]["raw_name"], "Mercurial Vapor 17 Academy TF")
        self.assertEqual(items[1]["sale_price"], 80700)

    def test_rule_based_filter_excludes_non_boots_and_extracts_series(self):
        parser_source = _cell_containing("def extract_product_items_from_candidate")
        parser_source = parser_source.split("\n\nproduct_items = extract_product_items", 1)[0]
        normalizer_source = _cell_containing("def normalize_product_item")
        normalizer_source = normalizer_source.split("\n\nnormalized_products", 1)[0]
        namespace = {
            "re": re,
            "_compact_spaces": lambda value: re.sub(r"\s+", " ", str(value or "")).strip(),
            "_excerpt": lambda value, limit=320: str(value or "")[:limit],
            "_extract_requested_price_range": lambda query: (100000, 199999),
            "_requested_brand_aliases": lambda query: ("\ub098\uc774\ud0a4", "nike"),
        }
        exec(parser_source, namespace)
        exec(normalizer_source, namespace)

        items = [
            {
                "input_index": 1,
                "seller": "\uc0ac\ucee4\ubd90",
                "seller_key": "soccerboom",
                "source_url": "https://soccerboom.co.kr",
                "source_title": "home",
                "source_rank": 1,
                "search_score": 0.7,
                "local_index": 1,
                "raw_name": "\ub098\uc774\ud0a4 ACG \ud0c0\uc6d4(FJ2366-012)",
                "brand": "\ub098\uc774\ud0a4",
                "consumer_price": 100000,
                "sale_price": 54900,
                "price_source": "sale_price_label",
                "evidence_text": "",
            },
            {
                "input_index": 2,
                "seller": "\uc0ac\ucee4\ubd90",
                "seller_key": "soccerboom",
                "source_url": "https://soccerboom.co.kr",
                "source_title": "home",
                "source_rank": 1,
                "search_score": 0.7,
                "local_index": 2,
                "raw_name": "\uc90c \uba38\ud050\ub9ac\uc5bc \ubca0\uc774\ud37c 16 \uc5d8\ub9ac\ud2b8 AG-PRO(IU3519-850)",
                "brand": "\ub098\uc774\ud0a4",
                "consumer_price": 339000,
                "sale_price": 186000,
                "price_source": "sale_price_label",
                "evidence_text": "",
            },
        ]

        filtered = namespace["filter_normalized_products"](items, "\ub098\uc774\ud0a4 10\ub9cc\uc6d0\ub300 AG \ucd95\uad6c\ud654")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["surface"], "AG-PRO")
        self.assertEqual(filtered[0]["series_name"], "\uba38\ud050\ub9ac\uc5bc \ubca0\uc774\ud37c 16")
        self.assertEqual(filtered[0]["sale_price"], 186000)

    def test_tavily_candidate_filter_uses_score_threshold_without_seller_top_k(self):
        code = "\n".join(_code_cells())

        self.assertIn("MIN_SCORE_THRESHOLD = 0.35", code)
        self.assertIn('if row.get("score", 0.0) < min_score:', code)
        self.assertIn('return "score_threshold"', code)

        removed_symbols = [
            "MIN_KEEP_PER_SELLER",
            "seller_top_k",
            "product_url_keyword",
            "score_keyword",
            "score_product_url",
            "min_keep_per_seller",
        ]
        for symbol in removed_symbols:
            self.assertNotIn(symbol, code)

    def test_agent_module_pipeline_test_cells_exist(self):
        code = "\n".join(_code_cells())

        self.assertIn("from Agent.product_search_agent import", code)
        self.assertIn("import importlib", code)
        self.assertIn("import Agent.product_search_agent as product_search_agent_module", code)
        self.assertIn("importlib.reload(product_search_agent_module)", code)
        self.assertIn("build_product_search_pipeline_result", code)
        self.assertIn("run_product_search_pipeline", code)
        self.assertIn("module_product_search_agent", code)
        self.assertIn("product_search_agent = module_product_search_agent", code)
        self.assertIn("agent_pipeline_from_current", code)
        self.assertIn("rejection_summary", code)
        self.assertIn("rejected_products", code)
        self.assertIn("agent_query", code)

    def test_code_cells_compile(self):
        for index, source in enumerate(_code_cells()):
            if source.lstrip().startswith("!"):
                continue
            compile(
                source,
                f"Product_Search.ipynb:code:{index}",
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )
