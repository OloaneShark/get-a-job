import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = (
    ROOT
    / "browser_extensions"
    / "jobfinitum_chrome_agent"
    / "greenhouse_agent.js"
)


class GreenhouseAgentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")

    def test_demographic_schema_is_part_of_question_normalization(self):
        self.assertIn(
            "schema?.demographic_questions",
            self.source,
        )
        self.assertIn(
            "`demographic_question_${questionId}`",
            self.source,
        )
        self.assertIn(
            "rawQuestion?.answer_options",
            self.source,
        )

    def test_generic_challenge_selectors_are_not_verification_signals(self):
        self.assertNotIn(
            "'iframe[title*=\"challenge\" i]'",
            self.source,
        )
        self.assertNotIn(
            "'[data-sitekey]'",
            self.source,
        )
        self.assertIn(
            "intersectsViewport",
            self.source,
        )


class GreenhouseAgentScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent tests.")

        harness = r"""
const fs = require("fs");
const vm = require("vm");

let source = fs.readFileSync(process.argv[1], "utf8");
source = source.replace(
  /\s*main\(\);\s*\}\)\(\);\s*$/,
  `
  globalThis.__jobfinitumTestHooks = {
    normalizedSchemaQuestions,
    visibleInteractiveVerificationChallenge,
  };
})();`
);

const context = {
  chrome: {
    runtime: {
      onMessage: {
        addListener() {},
      },
    },
  },
  console,
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);

const hooks = context.__jobfinitumTestHooks;
if (!hooks) {
  throw new Error("Could not expose Greenhouse Agent test hooks.");
}

const schema = {
  questions: [
    {
      label: "First Name",
      required: true,
      fields: [
        {name: "first_name", type: "input_text", values: []},
      ],
    },
  ],
  demographic_questions: {
    questions: [
      {
        id: 430,
        label: "What gender identity do you most closely identify with? ",
        required: true,
        type: "multi_value_multi_select",
        answer_options: [
          {id: 2183, label: "Female"},
          {id: 2181, label: "Male"},
          {id: 5382, label: "I don't wish to answer"},
        ],
      },
      {
        id: 431,
        label: "Are you a person of transgender experience? ",
        required: true,
        type: "multi_value_single_select",
        answer_options: [
          {id: 2186, label: "Yes"},
          {id: 2187, label: "No"},
        ],
      },
    ],
  },
};

const questions = hooks.normalizedSchemaQuestions(schema);

function element(rect, style, parentElement = null) {
  return {
    type: "",
    parentElement,
    getBoundingClientRect() {
      return rect;
    },
    getAttribute(name) {
      return name === "aria-hidden" ? null : null;
    },
  };
}

function challengeVisible(rect, ancestorStyle = null) {
  const ancestor = ancestorStyle
    ? element(rect, ancestorStyle)
    : null;
  const frame = element(
    rect,
    {display: "block", visibility: "visible", opacity: "1"},
    ancestor
  );

  context.window = {innerWidth: 1440, innerHeight: 900};
  context.document = {
    querySelectorAll(selector) {
      return selector.includes('recaptcha') && selector.includes('challenge')
        ? [frame]
        : [];
    },
  };
  context.getComputedStyle = (node) => (
    node === ancestor && ancestorStyle
      ? ancestorStyle
      : {display: "block", visibility: "visible", opacity: "1"}
  );

  return hooks.visibleInteractiveVerificationChallenge();
}

const offscreen = challengeVisible({
  left: -10000,
  right: -9400,
  top: -10000,
  bottom: -9400,
  width: 600,
  height: 600,
});

const hiddenAncestor = challengeVisible(
  {
    left: 400,
    right: 1000,
    top: 100,
    bottom: 700,
    width: 600,
    height: 600,
  },
  {display: "block", visibility: "hidden", opacity: "1"}
);

const onscreen = challengeVisible({
  left: 400,
  right: 1000,
  top: 100,
  bottom: 700,
  width: 600,
  height: 600,
});

process.stdout.write(JSON.stringify({
  questions,
  verification: {offscreen, hiddenAncestor, onscreen},
}));
"""

        completed = subprocess.run(
            [node, "-e", harness, str(AGENT_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.result = json.loads(completed.stdout)

    def test_demographic_questions_are_normalized_with_choices(self):
        questions = self.result["questions"]
        demographics = [
            question
            for question in questions
            if question["field_name"].startswith("demographic_question_")
        ]

        self.assertEqual(len(demographics), 2)
        self.assertEqual(demographics[0]["control_id"], "430")
        self.assertEqual(demographics[0]["type"], "multiselect")
        self.assertEqual(len(demographics[0]["choices"]), 3)
        self.assertEqual(demographics[1]["type"], "select")
        self.assertTrue(all(question["required"] for question in demographics))

    def test_only_an_onscreen_visible_challenge_pauses_the_runner(self):
        verification = self.result["verification"]

        self.assertFalse(verification["offscreen"])
        self.assertFalse(verification["hiddenAncestor"])
        self.assertTrue(verification["onscreen"])


if __name__ == "__main__":
    unittest.main()
