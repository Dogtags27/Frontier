"""D0 extraction prompt and schema. prompt_version is frozen for the bulk run."""

PROMPT_VERSION = "d0-6"
MODEL = "gpt-4.1-mini"
MAX_COMPLETION_TOKENS = 3000

FACET_KEYS = (
    "problems_addressed",
    "research_question",
    "techniques_used",
    "claimed_contributions",
    "datasets_evaluated",
    "baselines_compared",
    "scoring_measures",
    "experimental_setup",
    "reported_results",
    "quantitative_findings",
    "ablation_findings",
    "failure_cases",
    "stated_limits",
    "future_work",
    "assumptions_and_guarantees",
    "reproducibility_details",
)

SYSTEM = """# Role and Objective
Extract what one computer-science paper says about itself. Use only the numbered sentences in the user message. The sentences have had function words removed. Negation words are still there and they matter: not, no, never, without, cannot. Use the paper's own terms. Do not rename a method into a standard name it does not use.

# Item shape
Every list contains objects of the form {label, sentence_number}.
- label: the short name of one fact, under 12 words. It is the name we will store, not a copy of the sentence. A sentence often holds several facts. Pick the words that name this one fact.
- sentence_number: the integer in brackets before the supporting sentence, as in [4]. We use it later to read that sentence back. It is not a character offset, a page number, or a quote.
If no sentence supports an item, omit the item. If the paper does not say that kind of thing, return an empty list. Do not guess from general knowledge of the field.

# The sixteen lists

## problems_addressed
The difficulty this paper sets out to solve. The obstacle, not the question they ask about it.
Do not list application areas that the introduction only mentions as examples of the field.

## research_question
The question the authors investigate in order to address the problem. A problem is "models struggle with long-range dependencies." A research question is "does global attention improve long-range information propagation?"

## techniques_used
An algorithm, architecture, or method this paper uses or proposes.
A baseline it only compares against is not a technique. A dataset is not a technique. A measure is not a technique.

## claimed_contributions
What the authors say is new or valuable about this work. A contribution is "a new graph sampling algorithm." A technique is the algorithm itself. If the same words would appear in techniques_used, keep the method name there and put the novelty claim here only when the paper states one.

## datasets_evaluated
A named corpus or benchmark this paper builds or runs experiments on.
Do not include a dataset named only as background or prior work.

## baselines_compared
An existing method this paper compares its own method against. The paper's own method belongs in techniques_used, not here.

## scoring_measures
The name of a measure used to judge a result, such as top-5 error, mean average precision, F1, or ROC-AUC.
Put the measure name here. Put the numeric score in quantitative_findings.

## experimental_setup
How the experiment was run: dataset split, hardware, or model settings. "Official split over five seeds" belongs here when it describes the run.
A released code repository, a listed hyperparameter value, or a seed count stated so others can repeat the work belongs in reproducibility_details instead.

## reported_results
The conclusion the paper draws about performance or behavior. "The proposed method outperforms GIN" is a result.
The number that supports it is not a result. Put that number in quantitative_findings. One item per distinct conclusion. A second sentence that restates a conclusion already listed is a duplicate.

## quantitative_findings
A numeric result together with what is being compared and the condition, such as "ROC-AUC increased from 0.76 to 0.79 on OGB-MolHIV."
Do not also file that same number as a reported_result. A number from an ablation belongs in ablation_findings.

## ablation_findings
What changes when a component is removed or altered. "Removing structural positional encodings reduces ROC-AUC by 2 points."
Do not copy that item into quantitative_findings.

## failure_cases
An observed situation where the method fails, gets worse, or becomes impractical. "Performance degrades on graphs much larger than the training graphs."
A negation about the method (not, never, without, cannot) belongs here when the sentence reports a breakdown the authors observed.

## stated_limits
A boundary, assumption about scope, or caveat the authors acknowledge. "Experiments cover only molecular graph classification."
A stated limit is a boundary they declare. A failure case is a situation where they saw the method break. Do not put the same label in both lists. Keep the failure in failure_cases when they report an observed breakdown, and keep the boundary in stated_limits when they only name the scope.

## future_work
A direction the authors explicitly leave open. "Extend the method to dynamic graphs."
Future work is what remains. A claimed contribution is what they say they already did.

## assumptions_and_guarantees
A formal assumption, theoretical guarantee, correctness claim, or complexity bound. "Under the stated assumptions the algorithm terminates in polynomial time."
An informal caveat about the experiments belongs in stated_limits, not here.

## reproducibility_details
A detail a reader would need to repeat the work: code or data release, hyperparameter values, or random seeds. "The authors release code and use five random seeds."

# Duplicates
Do not restate an item you have already written. Before adding an item, check the list it would join and the lists named in the pairs above. If an existing item has the same meaning, or a label that is only a small rephrase, drop the new one. Similar technique names, repeated dataset mentions, and table cells that report the same comparison are duplicates. Keep the single clearest label and its sentence_number.

# Output length
The whole JSON object should stay under 1500 tokens. If you are near 1500 tokens, stop adding items. Prefer fewer distinct items over a long list of near-duplicates.

# Example
Sentence: "[4] normalisation not improve performance and increases memory."
- reported_results gets label "normalisation does not improve performance", sentence_number 4.
- failure_cases gets label "normalisation increases memory", sentence_number 4.
- Do not also put those labels in stated_limits.
Sentence: "[8] top-5 error falls from 8.1% to 6.7% on ILSVRC."
- scoring_measures gets label "top-5 error".
- quantitative_findings gets label "top-5 error 8.1% to 6.7% on ILSVRC", sentence_number 8.
- reported_results does not repeat that number.
Sentence: "[2] networks such as these have been used for detection, segmentation, and video."
- Those are not problems this paper addresses. Do not emit them."""

REMINDER = """# Final check
Use only the sentences above. Each item is {label, sentence_number}. label is a short name under 12 words, not a copy of the sentence. sentence_number is the integer in brackets.
problems_addressed is the difficulty. research_question is the question they investigate.
techniques_used is a method this paper uses. baselines_compared is a method it compares against. claimed_contributions is what they say is new.
datasets_evaluated is a set they build or test. scoring_measures is the measure name. quantitative_findings is the number, the comparison, and the condition.
reported_results is the conclusion, without repeating the number. ablation_findings is what changes when a component is removed.
failure_cases is an observed breakdown. stated_limits is a boundary they acknowledge. future_work is what they leave open.
assumptions_and_guarantees is a formal assumption or bound. experimental_setup is how the run was configured. reproducibility_details is code, seeds, or hyperparameters for repeating it.
Leave a list empty when the paper does not state that kind of thing. Do not add a duplicate. Keep the whole JSON under 1500 tokens."""

_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "sentence_number"],
    "properties": {
        "label": {
            "type": "string",
            "description": "Short name of this one fact, under 12 words, in the paper's terms. Not a copy of the whole sentence.",
        },
        "sentence_number": {
            "type": "integer",
            "description": "The number in brackets before the sentence that supports this label.",
        },
    },
}

_LISTS = {
    "problems_addressed": "Difficulties this paper sets out to solve. Not the research question, and not application areas mentioned only as background.",
    "research_question": "Questions the authors investigate. A question, not the difficulty it responds to.",
    "techniques_used": "Algorithms, architectures, or methods this paper uses or proposes. Not baselines, datasets, or measures.",
    "claimed_contributions": "What the authors say is new or valuable. Not a direction they leave for later.",
    "datasets_evaluated": "Named corpora or benchmarks this paper builds or runs experiments on. Not background datasets.",
    "baselines_compared": "Existing methods the paper compares against. Not the paper's own method.",
    "scoring_measures": "Names of measures used to judge results. Not the numeric scores.",
    "experimental_setup": "How the experiment was run: splits, hardware, or model settings.",
    "reported_results": "Conclusions about performance or behavior. Not the numeric evidence, and not a repeated table cell.",
    "quantitative_findings": "Numeric results with the comparison and the condition. Not ablation numbers.",
    "ablation_findings": "What changes when a component is removed or altered.",
    "failure_cases": "Observed situations where the method fails, degrades, or becomes impractical.",
    "stated_limits": "Boundaries or caveats the authors acknowledge. Not an observed breakdown already listed as a failure case.",
    "future_work": "Directions the authors explicitly leave open.",
    "assumptions_and_guarantees": "Formal assumptions, theoretical guarantees, correctness claims, or complexity bounds.",
    "reproducibility_details": "Code or data releases, hyperparameter values, or random seeds stated so the work can be repeated.",
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(FACET_KEYS),
    "properties": {
        key: {"type": "array", "description": description, "items": _ITEM}
        for key, description in _LISTS.items()
    },
}


def numbered(sentences):
    body = "\n".join(f"[{i}] {sentence}" for i, sentence in enumerate(sentences))
    return body + "\n\n" + REMINDER
