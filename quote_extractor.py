import re

def extract_quoted_text(text):
    # Step 1: Find all substrings in double quotes, including the quotes
    quoted_strings = re.findall(r'"[^"]*"', text)

    # Step 2: Remove HTML tags from inside the quoted text
    clean_quoted_strings = []
    for q in quoted_strings:
        inner = q[1:-1]  # remove the outer quotes
        inner_clean = re.sub(r'<[^>]+>', '', inner)  # strip HTML tags
        clean_quoted_strings.append(f'"{inner_clean}"')  # add quotes back

    return clean_quoted_strings

def main():
    print("Enter your text (press Enter twice to finish):")

    # Multiline input
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)

    input_text = "\n".join(lines)

    # Extract and clean quoted text
    results = extract_quoted_text(input_text)

    # Output
    if results:
        print("\nQuoted text found:")
        for quote in results:
            print(quote)
    else:
        print("No quoted text found.")

if __name__ == "__main__":
    main()
