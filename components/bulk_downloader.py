#!/usr/bin/python3
import html
import os
import re
from typing import Match, Optional, Pattern, Type, Union

import requests
from requests.models import Response

from . import constants
from .__version__ import __version__
from .chapter_downloader import chapterDownloader
from .jsonmaker import AccountJson, TitleJson
from .languages import getLangMD

headers = constants.HEADERS
domain = constants.MANGADEX_API_URL
re_regrex = re.compile(constants.REGEX)


# Connect to the API and get the data
def requestAPI(form: str, download_id: str) -> Optional[Response]:
    if form == 'rss':
        params = {}
        url = download_id
    else:    
        params = {'include': 'chapters'}
        url = domain.format(form, download_id)

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"Something went wrong. Error: {response.status_code}.")
        return
    return response


# Convert response data into a parsable json
def getData(response: Response) -> dict:
    data = response.json()
    data = data["data"]
    return data


# Get the amount of chapters
def getChapterCount(form: str, data: dict):
    if form in ('title', 'manga'):
        chapter_count = len(data["chapters"])
    else:
        chapter_count = data["group"]["chapters"] if form == 'group' else data["user"]["uploads"]

    # API displays a maximum of 6000 chapters
    if chapter_count > 6000:
        print(f'Due to API limits, a maximum of 6000 chapters can be downloaded for this {form}.')
    return


# Check if there are any chapters
def checkForChapters(chapters: list, form: str, download_id: str, name: str):
    if not chapters:
        print(f'{form.title()}: {download_id} - {name} has no chapters.')
        return False
    else:
        return True


# Print the download messages
def downloadMessage(status: bool, form: str, name: str):
    message = 'Downloading'
    if status:
        message = f'Finished {message}'

    print(f'{"-"*69}\n{message} {form.title()}: {name}\n{"-"*69}')
    return


# Check if a json exists
def getJsonData(title_json: Type[TitleJson]) -> list:
    if title_json.data_json:
        chapters_data = title_json.data_json["chapters"]
        return [c["id"] for c in chapters_data]
    else:
        return []


# Sort the chapter numbers naturally
def natsort(x) -> Union[int, float]:
	try:
		x = float(x)
	except ValueError:
		x = 0
	return x


# Get the chapter id and language from the rss feed
def rssItemFetcher(t: str, tag: str, regex: Pattern) -> Match:
    link = re.findall(f'<{tag}>.+<\/{tag}>', t)[0]
    link = link.replace(f'<{tag}>', '').replace(f'</{tag}>', '')
    match = re.match(regex, link).group(1)
    return match


# Filter out the unwanted chapters
def filterChapters(chapters: list, language: str) -> Optional[list]:
    chapters = [c for c in chapters if c["language"] == language]

    if not chapters:
        print(f'No chapters found in the selected language, {language}.')
        return
    return chapters


# Assign each volume a prefix, default: c
def getPrefixes(chapters: list) -> dict:
    volume_dict = {}
    chapter_prefix_dict = {}
    
    for c in chapters:
        volume_no = c["volume"]
        try:
            volume_dict[volume_no].append(c["chapter"])
        except KeyError:
            volume_dict[volume_no] = [c["chapter"]]

    list_volume_dict = list(reversed(list(volume_dict)))
    prefix = 'b'

    for volume in list_volume_dict:
        next_volume_index = list_volume_dict.index(volume) + 1
        previous_volume_index = list_volume_dict.index(volume) - 1
        result = False

        try:
            next_item = list_volume_dict[next_volume_index]
            result = any(elem in volume_dict[next_item] for elem in volume_dict[volume])
        except (KeyError, IndexError):
            previous_volume = list_volume_dict[previous_volume_index]
            result = any(elem in volume_dict[previous_volume] for elem in volume_dict[volume])

        if volume != '':
            if result:
                temp_json = {}
                temp_json[volume] = chr(ord(prefix) + next_volume_index)
                chapter_prefix_dict.update(temp_json)
            else:
                temp_json = {}
                temp_json[volume] = 'c'
                chapter_prefix_dict.update(temp_json)

    return chapter_prefix_dict


# Loop through the lists and get the chapters between the upper and lower bounds
def getChapterRange(chapters_list: list, chap_list: list) -> list:
    chapters_range = []

    for c in chap_list:
        if "-" in c:
            chapter_range = c.split('-')
            lower_bound = chapter_range[0].strip()
            upper_bound = chapter_range[1].strip()
            try:
                lower_bound_i = chapters_list.index(lower_bound)
            except ValueError:
                print(f'Chapter {lower_bound} does not exist. Skipping {c}.')
                continue
            try:
                upper_bound_i = chapters_list.index(upper_bound)
            except ValueError:
                print(f'Chapter {upper_bound} does not exist. Skipping {c}.')
                continue
            c = chapters_list[lower_bound_i:upper_bound_i+1]
        else:
            try:
                c = [chapters_list[chapters_list.index(c)]]
            except ValueError:
                print(f'Chapter {c} does not exist. Skipping.')
                continue
        chapters_range.extend(c)

    return chapters_range


# Check which chapters you want to download
def rangeChapters(chapters: list) -> list:
    chapters_list = list(set([c["chapter"] for c in chapters]))
    chapters_list.sort(key=natsort)

    print(f'Available chapters:\n{", ".join(chapters_list)}')

    remove_chapters = []

    chap_list = input("\nEnter the chapter(s) to download: ").strip()
    chap_list = [c.strip() for c in chap_list.split(',')]

    chapters_to_remove = [c.strip('!') for c in chap_list if '!' in c]
    [chap_list.remove(c) for c in chap_list if '!' in c]

    # Find which chapters to download
    if 'all' not in chap_list:
        chapters_to_download = getChapterRange(chapters_list, chap_list)
    else:
        chapters_to_download = chapters_list

    # Get the chapters to remove from the download list
    remove_chapters = getChapterRange(chapters_list, chapters_to_remove)

    [chapters_to_download.remove(i) for i in remove_chapters]
    chapters = [c for c in chapters if c["chapter"] in chapters_to_download]

    return chapters


# Download titles
def titleDownloader(
        download_id: Union[int, str],
        language: str,
        route: str,
        form: str,
        save_format: str,
        make_folder: bool,
        add_data: bool,
        covers: bool,
        range_download: bool,
        data: dict={},
        account_json: Type[AccountJson]=None):

    if form in ('title', 'manga'):
        download_type = 1
        response = requestAPI(form, download_id)
        if response is None:
            return

        data = getData(response)
        check = checkForChapters(data["chapters"], form, download_id, data["manga"]["title"])
        if not check:
            return

        getChapterCount(form, data)
    else:
        download_type = 2

    chapters = filterChapters(data["chapters"], language)
    if chapters is None:
        return

    chapter_prefix_dict = getPrefixes(chapters)

    title = re_regrex.sub('_', html.unescape(data["manga"]["title"]))
    title = title.rstrip()
    title = title.rstrip('.')
    title = title.rstrip()
    series_route = os.path.join(route, title)

    downloadMessage(0, form, title)

    if range_download:
        chapters = rangeChapters(chapters)

    # Initalise json classes and make series folders
    title_json = TitleJson(data, series_route, covers, download_type)

    chapters_data = getJsonData(title_json)

    # Loop chapters
    for chapter in chapters:
        chapter_id = chapter["id"]

        if chapter_id not in chapters_data:
            chapterDownloader(chapter_id, route, save_format, make_folder, add_data, chapter_prefix_dict, download_type, title, title_json, account_json)

    downloadMessage(1, form, title)

    # Save the json and covers if selected
    title_json.core(1)
    if download_type == 2:
        account_json.core(1)
    del title_json
    return


# Download group and user chapters
def groupUserDownloader(
        download_id: str,
        language: str,
        route: str,
        form: str,
        save_format: str,
        make_folder: bool,
        add_data: bool):

    response = requestAPI(form, download_id)
    if response is None:
        return

    data = getData(response)
    name = data["group"]["name"] if form == 'group' else data["user"]["username"]
    check = checkForChapters(data["chapters"], form, download_id, name)
    if not check:
        return

    getChapterCount(form, data)
    downloadMessage(0, form, name)

    # Initalise json classes and make series folders
    account_json = AccountJson(data, route, form)

    # Group the downloads by title
    titles = {}
    for chapter in data["chapters"]:
        if chapter["mangaId"]in titles:
            titles[chapter["mangaId"]]["chapters"].append(chapter)
        else:
            titles[chapter["mangaId"]] = {"manga": {"id": chapter["mangaId"], "title": chapter["mangaTitle"]}, "chapters": []}
            titles[chapter["mangaId"]]["chapters"].append(chapter)

    for title in titles:
        titleDownloader(title, language, route, form, save_format, make_folder, add_data, False, False, titles[title], account_json)

    downloadMessage(1, form, name)

    # Save the json
    account_json.core(1)
    del account_json
    return


# Download rss feeds
def rssDownloader(
        url: str,
        language: str,
        route: str,
        save_format: str,
        make_folder: bool,
        add_data: bool):

    response = requestAPI('rss', url)
    data = response.content.decode()
    chapters = []

    # Find the chapter links and remove everything other than the ids and language
    items = re.findall(r'<item>.+</item>', data, re.DOTALL)
    for i in items:
        links = i.split("<item>")
        for l in links:
            tags = re.findall(r'<.+>.+<\/.+>', l, re.DOTALL)
            for t in tags:
                temp_dict = {}
                temp_dict["id"] = rssItemFetcher(t, 'link', r'.+\/(\d+)')

                lang_name = rssItemFetcher(t, 'description', r'.+Language:\s(.+)')
                lang_id = getLangMD(lang_name)
                temp_dict["language"] = lang_id

                chapters.append(temp_dict)

    chapters = filterChapters(chapters, language)
    if chapters is None:
        return

    downloadMessage(0, 'rss', 'This will only download chapters of the language selected, default: English.')

    for chapter in chapters:
        chapter = chapter["id"]
        chapterDownloader(chapter, route, save_format, make_folder, add_data)
    
    downloadMessage(1, 'rss', 'MangaDex')
    return