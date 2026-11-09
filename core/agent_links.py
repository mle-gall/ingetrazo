# SPDX-License-Identifier: GPL-3.0-or-later
"""Link and project inspection uses the same operations as the project browser."""
from core import links, project


class LinkTools:
    def _tool_query_links(self):
        return links.query(self._viewport.scene)

    def _tool_link_document(self, path, select=None):
        group = self._viewport.window().link_igz_path(path, at=(0, 0, 0), select=select)
        return {'uid': group.uid}

    def _tool_reload_link(self, path):
        window = self._viewport.window()
        links.reload(self._viewport.scene, path, getattr(window, '_current_path', None))
        window._relink_done('Linked document reloaded')
        return self._tool_query_links()

    def _tool_query_project(self):
        return project.read(self._viewport.scene)

    def _tool_set_project(self, path):
        window = self._viewport.window()
        return project.attach(self._viewport.scene, path, getattr(window, '_current_path', None))

    def _tool_query_worksession(self):
        return self._viewport.window().query_worksession()

    def _tool_set_active_file(self, path):
        return self._viewport.window().set_active_file(path)

    def _tool_open_project(self, path):
        window = self._viewport.window()
        window.open_project(path)
        return window.query_worksession()

    def _tool_query_recent(self):
        from core.recent import query
        return query()
