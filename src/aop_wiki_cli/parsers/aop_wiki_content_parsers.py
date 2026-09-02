"""Parsers for non-XML AOP-Wiki content inputs."""

import difflib


TITLE_SKIP_WORDS = [
	"the",
	"and",
	"of",
	"in",
	"to",
	"function"
]

AOP_WIKI_ACTION_TERMS = [
	"increased",
	"decreased",
	"functional change",
	"abnormal",
	"pathological",
	"occurrence",
	"disrupted",
	"morphological change",
	"arrested",
	"delayed",
	"premature"
]

SUPPLEMENTAL_ACTION_TERMS = [
	"activation",
	"inhibition",
	"suppression",
	"enhancement",
	"impairment",
	"altered",
	"alteration",
	"modulation",
	"loss",
	"aberrant",
	"reduced",
	"agonism",
	"antagonism",
	"blockade",
	"n/a"
]

ALL_ACTION_TERMS = AOP_WIKI_ACTION_TERMS + SUPPLEMENTAL_ACTION_TERMS


def _drop_terms(title, terms_to_drop):
	title_words = title.split(' ')
	words_to_keep = []
	for word in title_words:
		if word.lower() in terms_to_drop:
			continue
		elif difflib.get_close_matches(word.lower(), terms_to_drop, n=1, cutoff=0.7):
			continue
		else:
			words_to_keep.append(word)

	return ' '.join(words_to_keep)


def _drop_context_terms(title, biological_context_terms_to_drop):
	cleaned_title = title
	for phrase in biological_context_terms_to_drop:
		if phrase in cleaned_title.lower():
			cleaned_title = cleaned_title.lower().replace(phrase, '').strip()
	return ' '.join(cleaned_title.split())


def strip_event_titles(event_ids_and_titles, biological_context_terms_to_drop, drop_action_terms=True):
	"""
	Strip action/context terms from event titles to focus on biological objects/processes.

	Args:
		event_ids_and_titles: List of dicts, each with at least a 'title' key.
		biological_context_terms_to_drop: Terms to remove from titles.
		drop_action_terms: Whether to remove action terms (default True).

	Returns:
		List of dicts with 'stripped_title' key added to each entry.
	"""
	event_ids_and_titles_with_stripped_titles = []
	for detatils in event_ids_and_titles:
		title = detatils["title"]
		title_without_action = _drop_terms(title, ALL_ACTION_TERMS) if drop_action_terms else title
		title_without_context = _drop_context_terms(title_without_action, biological_context_terms_to_drop)

		words = title_without_context.split(' ')
		if words and words[0].lower() in TITLE_SKIP_WORDS:
			words = words[1:]
		if words and words[-1].lower() in TITLE_SKIP_WORDS:
			words = words[:-1]
		detatils["stripped_title"] = ' '.join(words)
		event_ids_and_titles_with_stripped_titles.append(detatils)

	return event_ids_and_titles_with_stripped_titles

