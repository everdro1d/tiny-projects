from bs4 import BeautifulSoup
import random
import tldextract
import time
import requests
import re
import os
# TODO: add support for relative urls => keep in mind href targets

def main():
    # get user home dir
    path = input("Pick save directory (Def: Desktop): ")
    path = os.path.expanduser('~/Desktop')
    os.chdir(path)

    # site to scrape
    url = input("Enter URL: ")

    # options
    option = input(
        "Pick an option:\n"
        + "1. get urls(page)\n"
        + "2. get text(page)\n"
        + "3. get all urls matching root domain(page)\n"
        + "4. get urls(site-wide)\n"
        + "5. get all urls matching root domain(site-wide)\n"
        + "6. get text(site-wide)\n"
        + "7. get raw(page)\n"
    )
    option = int(option)

    page_content = get_page_content(url)
    root_domain = tldextract.extract(url).registered_domain

    global base_domain
    tmp = url.split("/")
    to_remove = "/" + tmp[tmp.__len__()-1]
    base_domain = url.replace(to_remove, "")

    if option == 1:
        # get all urls on page
        urls = get_urls(page_content, allow_duplicates())

        if urls:
            with open("page_urls.txt", "w") as file_object:
                file_object.write("\n".join(urls))
            print("URLS on page saved to file")
        else:
            print("Failed to find any urls on page")

    elif option == 2:
        # get all text on page
        content = get_text(page_content)
        if page_content:
            with open("page_text.txt", "w") as file_object:
                file_object.write(content)
            print("Saved text on page to file")
        else:
            print("Failed to find text on page")

    elif option == 3:
        # get urls for all urls with same root url
        root_urls = get_all_root_urls_on_page(page_content, root_domain)
        if root_urls:
            with open("same_site_urls.txt", "w") as file_object:
                file_object.write("\n".join(root_urls))
            print("Saved urls to same site to file")
        else:
            print("Failed to find urls to same site on this page")

    elif option == 4:
        # get all urls on whole site
        urls = get_all_urls_on_site(page_content, allow_duplicates(), root_domain)
        if urls:
            with open("site_urls.txt", "w") as file_object:
                file_object.write("\n".join(urls))
            print("URLS on site saved to file")
        else:
            print("Failed to find any urls on site")

    elif option == 5:
        root_urls = get_all_root_urls_on_page(page_content, root_domain)
        if root_urls:
            with open("root_domain_site_map.txt", "w") as file_object:
                file_object.write("\n".join(root_urls))
            print("Saved urls on root domain to file")
        else:
            print("Failed to find urls with same root domain")

    elif option == 6:
        # get all text on whole site
        full_text = get_all_text_on_site(page_content, root_domain)

        if full_text:
            with open("site_text.txt", "w") as file_object:
                file_object.write(full_text)
            print("Saved text on site to file")
        else:
            print("Failed to find text on site")

    elif option == 7:
        # get raw page
        if page_content:
            with open("page_raw_text.txt", "w") as file_object:
                file_object.write(page_content)
            print("Saved raw page to file")
        else:
            print("Failed to retrieve raw of site")

    else:
        print("Invalid option. Please choose again.")


def get_urls(page_content, allow_duplicates):
    urls = re.findall(r"https?://\S+", page_content)
#    for a in BeautifulSoup(page_content, "html.parser").find_all("a"):
#        url = a.get("href")
#        # elim non urls
#        if url is None or not url.__contains__("/"):
#            continue
#
#        if not url.startswith("http"):
#            sep = ""
#            if not url.startswith("/"):
#                sep = "/"
#
#            url = base_domain + sep + url
#
#        urls.append(url)

    cleaned_urls = [clean_url(url) for url in urls]

    if not allow_duplicates:
        cleaned_urls = list(set(cleaned_urls))

    return cleaned_urls


def clean_url(url):
    patterns = [
        r"<.*?>",
        r"\"?>.*",
        r"[');\"<>,]",
        r"/$",
        r"%20.*" if "family=Open" not in url else ""
    ]

    for pattern in patterns:
        url = re.sub(pattern, "", url)

    return url


def get_all_root_urls_on_page(page_content, root_domain):
    tmp_urls = get_urls(page_content, False)

    if root_domain not in tmp_urls:
        tmp_urls.append(root_domain)

    root_urls = [url for url in tmp_urls if root_domain in url]

    return root_urls


def get_all_urls_on_site(site_content, allow_duplicates, root_domain):
    # iterate through root urls grabbing all root urls on entire site
    root_urls = get_all_root_urls_on_page(site_content, root_domain)
    for root_url in root_urls:
        root_urls.append(get_all_root_urls_on_page(site_content, root_domain))
    # remove duplicates
    urls = list(set(root_urls))
    index = 0
    # iterate through all urls on site
    for url in urls:
        print(index)
        index += 1
        urls_page = get_urls(get_page_content(url), allow_duplicates)
        urls.append(urls_page)

    return urls


def get_all_root_urls_on_site(page_content, root_domain):
    urls = get_all_urls_on_site(page_content, False, root_domain)

    root_urls = [url for url in urls if root_domain in url]
    return root_urls


def allow_duplicates():
    allow_str = input("Allow duplicates? (y/N): ")
    return allow_str.lower().__contains__('y')


def get_text(page_content):
    # isolate text from html
    tmp_str = BeautifulSoup(page_content, "html.parser").get_text()
    # clean up extra \n
    return re.sub(r"\n\s*\n", "\n\n", tmp_str).strip()


def get_all_text_on_site(site_content, root_domain):
    full_text = ""
    for url in get_all_root_urls_on_site(site_content, root_domain):
        full_text.append(get_text(get_page_content(url)))

    return full_text


def get_page_content(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
    }

    time.sleep(random.randrange(2, 6))
    response = requests.get(url, headers=headers).text
    return response


main()
