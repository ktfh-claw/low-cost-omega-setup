.PHONY: test run clean

# Unit tests (gate faked; no binary, no network, no docker needed).
# Integration cases activate when DAS_SYNTAX_CHECK_BIN points at a real
# syntax_check binary; they skip cleanly otherwise.
test:
	python3 -m pytest tests/ -q

# Full pipeline on a sample history file (see README.md for the full
# argument set); the campaign/source/epoch provenance params are
# campaign-verified examples.
run:
	python3 import_wrapper.py \
		--input history.metta \
		--out load.metta \
		--report report.json \
		--campaign omega-das-bridge \
		--source history-v1 \
		--epoch epoch-1

clean:
	rm -f load.metta report.json
