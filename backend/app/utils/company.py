def normalize_company_name(name: str) -> str:
    name = name.lower().strip()
    # Step 1: strip trailing punctuation FIRST
    # Important: "google inc." becomes "google inc" here — so the suffix list
    # must include both "inc." AND "inc" to handle both orderings robustly.
    name = name.rstrip(".,;:")
    # Step 2: strip legal suffixes — loop until no more matches
    # Single-pass loop fails on "Google Inc. LLC" (strips "llc", misses "inc.")
    suffixes = ["llc", "inc.", "inc", "corp.", "corp", "ltd.", "ltd",
                "limited", "co.", "co"]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if name.endswith(f" {suffix}"):
                name = name[: -(len(suffix) + 1)].rstrip()
                changed = True
                break  # restart the loop after each match
    return name
