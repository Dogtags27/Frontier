UPDATE orgs SET name = left(name, length(name) - 8) || '''s Team' WHERE right(name, 8) = '''s class';
