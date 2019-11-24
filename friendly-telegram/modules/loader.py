#    Friendly Telegram (telegram userbot)
#    Copyright (C) 2018-2019 The Authors

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import importlib
import sys
import uuid
import asyncio
import urllib

from importlib.machinery import ModuleSpec
from importlib.abc import SourceLoader

import requests

from .. import loader, utils
from ..compat import uniborg

logger = logging.getLogger(__name__)


def register(cb):  # pylint: disable=C0116
    cb(LoaderMod())


class StringLoader(SourceLoader):  # pylint: disable=W0223 # False positive, implemented in SourceLoader
    """Load a python module/file from a string"""
    def __init__(self, data, origin):
        if isinstance(data, str):
            self.data = data.encode("utf-8")
        else:
            self.data = data
        self.origin = origin

    def get_code(self, fullname):
        source = self.get_source(fullname)
        if source is None:
            return None
        return compile(source, self.origin, "exec", dont_inherit=True)

    def get_filename(self, fullname):
        return self.origin

    def get_data(self, filename):  # pylint: disable=W0221,W0613
        # W0613 is not fixable, we are overriding
        # W0221 is a false positive assuming docs are correct
        return self.data


def unescape_percent(text):
    i = 0
    ln = len(text)
    is_handling_percent = False
    out = ""
    while i < ln:
        char = text[i]
        if char == "%" and not is_handling_percent:
            is_handling_percent = True
            i += 1
            continue
        if char == "d" and is_handling_percent:
            out += "."
            is_handling_percent = False
            i += 1
            continue
        out += char
        is_handling_percent = False
        i += 1
    return out


@loader.tds
class LoaderMod(loader.Module):
    """Loads modules"""
    strings = {"name": "Loader",
               "repo_config_doc": "Fully qualified URL to a module repo",
               "avail_header": "<b>Available official modules from repo</b>",
               "select_preset": "<code>Please select a preset</code>",
               "no_preset": "<code>Preset not found</code>",
               "preset_loaded": "<code>Preset loaded</code>",
               "no_module": "<code>Module not available in repo.</code>",
               "no_file": "<code>File not found</code>",
               "provide_module": "<code>Provide a module to load</code>",
               "bad_unicode": "<code>Invalid Unicode formatting in module</code>",
               "load_failed": "<code>Loading failed. See logs for details</code>",
               "loaded": "<code>Module loaded.</code>",
               "no_class": "<code>What class needs to be unloaded?</code>",
               "unloaded": "<code>Module unloaded.</code>",
               "not_unloaded": "<code>Module not unloaded.</code>"}

    def __init__(self):
        super().__init__()
        self.config = loader.ModuleConfig("MODULES_REPO",
                                          "https://raw.githubusercontent.com/friendly-telegram/modules-repo/master",
                                          lambda: self.strings["repo_config_doc"])
        self._pending_setup = []

    async def dlmodcmd(self, message):
        """Downloads and installs a module from the official module repo"""
        args = utils.get_args(message)
        if args:
            if await self.download_and_install(args[0], message):
                self._db.set(__name__, "loaded_modules",
                             list(set(self._db.get(__name__, "loaded_modules", [])).union([args[0]])))
        else:
            text = utils.escape_html("\n".join(await self.get_repo_list("full")))
            await utils.answer(message, "<b>" + self.strings["avail_header"] + "</b>\n<code>" + text + "</code>")

    async def dlpresetcmd(self, message):
        """Set preset. Defaults to full"""
        args = utils.get_args(message)
        if not args:
            await utils.answer(message, self.strings["select_preset"])
            return
        try:
            await self.get_repo_list(args[0])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                await utils.answer(message, self.strings["no_preset"])
                return
            else:
                raise
        self._db.set(__name__, "chosen_preset", args[0])
        self._db.set(__name__, "loaded_modules", [])
        self._db.set(__name__, "unloaded_modules", [])
        await utils.answer(message, self.strings["preset_loaded"])

    async def _get_modules_to_load(self):
        todo = await self.get_repo_list(self._db.get(__name__, "chosen_preset", None))
        todo = todo.difference(self._db.get(__name__, "unloaded_modules", []))
        todo.update(self._db.get(__name__, "loaded_modules", []))
        return todo

    async def get_repo_list(self, preset=None):
        if preset is None:
            preset = "full"
        r = await utils.run_sync(requests.get, self.config["MODULES_REPO"] + "/" + preset + ".txt")
        r.raise_for_status()
        return set(filter(lambda x: x, r.text.split("\n")))

    async def download_and_install(self, module_name, message=None):
        if urllib.parse.urlparse(module_name).netloc:
            url = module_name
        else:
            url = self.config["MODULES_REPO"] + "/" + module_name + ".py"
        r = await utils.run_sync(requests.get, url)
        if r.status_code == 404:
            if message is not None:
                await utils.answer(message, self.strings["no_module"])
            return False
        r.raise_for_status()
        return await self.load_module(r.content, message, module_name, url)

    async def loadmodcmd(self, message):
        """Loads the module file"""
        if message.file:
            msg = message
        else:
            msg = (await message.get_reply_message())
        if msg is None or msg.media is None:
            args = utils.get_args(message)
            if args:
                try:
                    path = args[0]
                    with open(path, "rb") as f:
                        doc = f.read()
                except FileNotFoundError:
                    await utils.answer(message, self.strings["no_file"])
                    return
            else:
                await utils.answer(message, self.strings["provide_module"])
                return
        else:
            path = None
            doc = await msg.download_media(bytes)
        logger.debug("Loading external module...")
        try:
            doc = doc.decode("utf-8")
        except UnicodeDecodeError:
            await utils.answer(message, self.strings["bad_unicode"])
            return
        if path is not None:
            await self.load_module(doc, message, origin=path)
        else:
            await self.load_module(doc, message)

    async def load_module(self, doc, message, name=None, origin="<string>"):
        if name is None:
            uid = "__extmod_" + str(uuid.uuid4())
        else:
            uid = name.replace("%", "%%").replace(".", "%d")
        module_name = "friendly-telegram.modules." + uid
        try:
            module = importlib.util.module_from_spec(ModuleSpec(module_name, StringLoader(doc, origin), origin=origin))
            sys.modules[module_name] = module
            module.borg = uniborg.UniborgClient(module_name)
            module._ = _
            module.__spec__.loader.exec_module(module)
        except Exception:  # That's okay because it might try to exit or something, who knows.
            logger.exception("Loading external module failed.")
            if message is not None:
                await utils.answer(message, self.strings["load_failed"])
            return False
        if "register" not in vars(module):
            if message is not None:
                await utils.answer(message, self.strings["load_failed"])
            logging.error("Module does not have register(), it has " + repr(vars(module)))
            return False
        try:
            try:
                module.register(self.register_and_configure, module_name)
            except TypeError:
                module.register(self.register_and_configure)
            await self._pending_setup.pop()
        except Exception:
            logger.exception("Module threw")
            if message is not None:
                await utils.answer(message, self.strings["load_failed"])
            return False
        if message is not None:
            await utils.answer(message, self.strings["loaded"])
        return True

    def register_and_configure(self, instance):
        self.allmodules.register_module(instance)
        self.allmodules.send_config_one(instance, self._db)
        self._pending_setup.append(self.allmodules.send_ready_one(instance, self._client, self._db, self.allclients))

    async def unloadmodcmd(self, message):
        """Unload module by class name"""
        args = utils.get_args(message)
        if not args:
            await utils.answer(message, self.strings["what_class"])
            return
        clazz = args[0]
        worked = self.allmodules.unload_module(clazz)
        without_prefix = []
        for mod in worked:
            assert mod.startswith("friendly-telegram.modules."), mod
            without_prefix += [unescape_percent(mod[len("friendly-telegram.modules."):])]
        it = set(self._db.get(__name__, "loaded_modules", [])).difference(without_prefix)
        self._db.set(__name__, "loaded_modules", list(it))
        it = set(self._db.get(__name__, "unloaded_modules", [])).union(without_prefix)
        self._db.set(__name__, "unloaded_modules", list(it))
        if worked:
            await utils.answer(message, self.strings["unloaded"])
        else:
            await utils.answer(message, self.strings["not_unloaded"])

    async def _update_modules(self):
        todo = await self._get_modules_to_load()
        await asyncio.gather(*[self.download_and_install(mod) for mod in todo])

    async def client_ready(self, client, db):
        self._db = db
        self._client = client
        await self._update_modules()
