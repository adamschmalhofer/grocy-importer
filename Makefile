
test:
	mypy --strict grocy_importer.py
	python3 -mdoctest grocy_importer.py
	for file in README.rst tests/README.rst; do \
		clitest --prefix '    ' \
			--pre-flight "cp tests/setup/todo.txt.orig tests/setup/todo.txt; alias todo-txt='todo-txt -Na -d tests/setup/todo.cfg -p'" \
			$$file; \
		rst2html $$file /dev/null; \
	done
	flake8 grocy_importer.py
