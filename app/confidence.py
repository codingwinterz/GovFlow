"""The one review rule for confidence, used everywhere a reading is accepted or withheld.

A reading at or below the scheme's confidence_threshold goes to human review. "At" is included on purpose: on
17 Nov 2026 the model copied LA-11's damaged name "L?ta Sh1rodkar" at exactly 0.85 and it was accepted.
"""


def needs_review_for_confidence(confidence: float, threshold: float) -> bool:
    return confidence <= threshold
