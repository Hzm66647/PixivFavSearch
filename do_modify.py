import sys

print("Step 1: Reading preview HTML...")
with open("C:/temp/PixivFavSearch-unified.html", "r", encoding="utf-8") as f:
    preview = f.read()
preview_lines = preview.split("\n")

# Extract CSS (lines 2-192 in 1-indexed = indices 1-191)
preview_css = "\n".join(preview_lines[1:192]).strip()
# Extract HTML body (lines 194-345 in 1-indexed = indices 193-344)
preview_html = "\n".join(preview_lines[193:345]).strip()
# Extract keyframes (lines 488-490 in 1-indexed = indices 487-489)
preview_keyframes = "\n".join(preview_lines[487:490]).strip()

print(f"  CSS: {len(preview_css)} chars")
print(f"  HTML: {len(preview_html)} chars")
print(f"  Keyframes: {len(preview_keyframes)} chars")

print("\nStep 2: Reading new JS...")
with open("C:/temp/Hermes/PixivFavSearch/new_js.txt", "r", encoding="utf-8") as f:
    new_js = f.read()
print(f"  JS: {len(new_js)} chars")

print("\nStep 3: Building new INDEX...")
new_index = '<meta charset="UTF-8"><title>PixivFavSearch — 整合版</title><style>\n' + preview_css + '</style>\n\n' + preview_html + '\n\n' + new_js + '\n\n' + preview_keyframes
print(f"  New INDEX: {len(new_index)} chars")

print("\nStep 4: Reading current server file...")
with open("C:/temp/Hermes/PixivFavSearch/pix_search_server.py", "r", encoding="utf-8") as f:
    full_content = f.read()
full_lines = full_content.split("\n")
print(f"  Total lines: {len(full_lines)}")

print("\nStep 5: Finding INDEX boundaries...")
index_start_line = None
index_end_line = None

for i, line in enumerate(full_lines):
    if line.startswith('INDEX = r"""'):
        index_start_line = i
    elif index_start_line is not None and line.strip() == '"""' and i > index_start_line:
        index_end_line = i
        break

if index_start_line is None:
    print("ERROR: Could not find INDEX start!")
    sys.exit(1)
if index_end_line is None:
    print("ERROR: Could not find INDEX end!")
    sys.exit(1)

print(f"  INDEX starts at line {index_start_line + 1}, ends at line {index_end_line + 1}")

print("\nStep 6: Building new file content...")
before_index = full_lines[:index_start_line]
after_index = full_lines[index_end_line + 1:]

# The INDEX line content (using raw string, so we need to escape backslashes)
escaped_index = new_index.replace('\\', '\\\\')
new_index_line = 'INDEX = r"""' + escaped_index + '"""'

new_content = "\n".join(before_index) + "\n" + new_index_line + "\n" + "\n".join(after_index)
print(f"  New file line count: {len(new_content.split(chr(10)))}")

print("\nStep 7: Writing new file...")
with open("C:/temp/Hermes/PixivFavSearch/pix_search_server.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("  Done! File written successfully.")
print("\nStep 8: Verification...")
with open("C:/temp/Hermes/PixivFavSearch/pix_search_server.py", "r", encoding="utf-8") as f:
    verify = f.read()
if 'INDEX = r"""' in verify and 'async function renderWall' in verify:
    print("  INDEX found and JS contains async API calls")
else:
    print("  Verification failed!")
    sys.exit(1)

print("\nAll done!")