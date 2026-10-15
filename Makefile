.PHONY: clean-pyc clean-build docs test coverage lint typecheck check build install

clean: clean-build clean-pyc


clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info


clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +

install:
	uv sync

build:
	uv build

docs:
	$(MAKE) -C docs html

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy

check: lint typecheck test

coverage:
	uv run --with pytest-cov pytest --cov=livereload --cov-report=html
