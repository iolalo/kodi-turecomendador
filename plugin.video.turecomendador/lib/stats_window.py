from __future__ import annotations
import os

import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))

ACTION_BACK = (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU,
               xbmcgui.ACTION_PARENT_DIR)


def _bar(value: int, max_val: int, width: int = 22) -> str:
    if max_val == 0:
        return "░" * width
    filled = max(0, min(width, round(value * width / max_val)))
    return "█" * filled + "░" * (width - filled)


def _generate_story(s: dict, period_label: str) -> str:
    total_min = s.get("total_minutes", 0)
    total_h = total_min // 60
    total_days = round(total_min / 1440, 1)
    unique_m = s.get("unique_movies", 0)
    episodes = s.get("episodes", 0)
    shows = s.get("shows", 0)
    top_dirs = s.get("top_directors", [])
    top_genres = s.get("top_genres", [])

    # Primera frase: tiempo total
    if total_days >= 1:
        frase1 = f"En {period_label} consumiste {total_days} días de contenido ({total_h}h en total)"
    elif total_h > 0:
        frase1 = f"En {period_label} dedicaste {total_h}h a películas y series"
    else:
        return ""

    # Desglose películas/series
    if unique_m and episodes:
        frase1 += f" — {unique_m} películas y {episodes} episodios en {shows} series."
    elif unique_m:
        frase1 += f" — {unique_m} películas."
    elif episodes:
        frase1 += f" — {episodes} episodios en {shows} series."
    else:
        frase1 += "."

    # Segunda frase: director + género
    insights = []
    if top_dirs:
        name, count = top_dirs[0]
        suf = "película" if count == 1 else "películas"
        insights.append(f"Tu director más frecuente: {name} ({count} {suf})")
    if top_genres and len(top_genres) >= 2:
        insights.append(f"géneros dominantes: {top_genres[0][0]} y {top_genres[1][0]}")
    elif top_genres:
        insights.append(f"género dominante: {top_genres[0][0]}")

    frase2 = (". ".join(insights) + ".") if insights else ""
    return (frase1 + "  " + frase2).strip()


def _generate_story_alltime(s: dict) -> str:
    movies_d = s.get("movies", {})
    ep_d = s.get("episodes", {})
    sh_d = s.get("shows", {})
    rat_d = s.get("ratings", {})

    m_watched = movies_d.get("watched", 0)
    m_min = movies_d.get("minutes", 0)
    ep_watched = ep_d.get("watched", 0)
    ep_min = ep_d.get("minutes", 0)
    sh_watched = sh_d.get("watched", 0)
    total_days = round((m_min + ep_min) / 1440, 1)
    total_h = (m_min + ep_min) // 60
    total_ratings = rat_d.get("total", 0)

    if total_days >= 1:
        frase1 = f"Llevas {total_days} días de contenido acumulado ({total_h}h) — {m_watched} películas y {ep_watched} episodios en {sh_watched} series."
    elif total_h > 0:
        frase1 = f"Tu historial acumula {total_h}h — {m_watched} películas y {ep_watched} episodios."
    else:
        return ""

    if total_ratings > 0:
        frase2 = f"Calificaste {total_ratings} títulos en Trakt."
    else:
        frase2 = ""

    return (frase1 + "  " + frase2).strip()


class StatsDialog(xbmcgui.WindowXML):
    """Custom stats window loaded from DialogStats.xml."""

    stats_data: dict = {}
    period_label: str = ""
    is_all_time: bool = False

    def _lbl(self, control_id: int, text: str):
        try:
            self.getControl(control_id).setLabel(text)
        except Exception:
            pass

    def onInit(self):
        self._lbl(1, f"ESTADÍSTICAS — {self.period_label.upper()}")
        if self.is_all_time:
            self._fill_all_time(self.stats_data)
        else:
            self._fill_period(self.stats_data)

    def _fill_period(self, s: dict):
        unique_m = s.get("unique_movies", 0)
        plays_m = s.get("plays_movies", 0)
        movie_h = s.get("movie_minutes", 0) // 60
        movie_min = s.get("movie_minutes", 0) % 60
        episodes = s.get("episodes", 0)
        shows = s.get("shows", 0)
        ep_h = s.get("episode_minutes", 0) // 60
        total_min = s.get("total_minutes", 0)
        total_h = total_min // 60
        total_m = total_min % 60
        total_days = round(total_min / 1440, 1)

        self._lbl(100, str(unique_m))
        self._lbl(101, "películas únicas")
        self._lbl(102, f"{plays_m} reproducciones   •   {movie_h}h {movie_min}min")

        self._lbl(200, str(shows))
        self._lbl(201, "shows distintos")
        self._lbl(202, f"{episodes} episodios")
        self._lbl(203, f"{ep_h}h estimadas")

        self._lbl(300, f"{total_h}h {total_m}min")
        self._lbl(301, f"{total_days} días de contenido")

        # Genre bars in right column
        self._lbl(390, "[ GÉNEROS ]")
        genres = s.get("top_genres", [])
        slots = [(400, 401, 402), (410, 411, 412), (420, 421, 422),
                 (430, 431, 432), (440, 441, 442)]
        max_g = genres[0][1] if genres else 1
        for i, (id_n, id_b, id_c) in enumerate(slots):
            if i < len(genres):
                name, count = genres[i]
                self._lbl(id_n, name)
                self._lbl(id_b, _bar(count, max_g))
                self._lbl(id_c, str(count))
            else:
                self._lbl(id_n, ""); self._lbl(id_b, ""); self._lbl(id_c, "")

        # Director list
        self._lbl(490, "[ TOP DIRECTORES ]")
        dirs = s.get("top_directors", [])
        dir_slots = [(500, 501), (510, 511), (520, 521), (530, 531), (540, 541)]
        for i, (id_n, id_c) in enumerate(dir_slots):
            if i < len(dirs):
                name, count = dirs[i]
                suffix = "película" if count == 1 else "películas"
                self._lbl(id_n, f"{i+1}. {name}")
                self._lbl(id_c, f"{count} {suffix}")
            else:
                self._lbl(id_n, ""); self._lbl(id_c, "")

        # Storytelling narrative
        self._lbl(700, _generate_story(s, self.period_label))

        # Clear ratings section
        self._lbl(600, "")
        for i in range(601, 611):
            self._lbl(i, "")

    def _fill_all_time(self, s: dict):
        movies_d = s.get("movies", {})
        ep_d = s.get("episodes", {})
        sh_d = s.get("shows", {})
        rat_d = s.get("ratings", {})

        m_watched = movies_d.get("watched", 0)
        m_plays = movies_d.get("plays", 0)
        m_min = movies_d.get("minutes", 0)
        m_h = m_min // 60
        m_days = round(m_min / 1440, 1)

        ep_watched = ep_d.get("watched", 0)
        ep_plays = ep_d.get("plays", 0)
        ep_min = ep_d.get("minutes", 0)
        ep_h = ep_min // 60
        sh_watched = sh_d.get("watched", 0)

        total_min = m_min + ep_min
        total_h = total_min // 60
        total_days = round(total_min / 1440, 1)

        self._lbl(100, str(m_watched))
        self._lbl(101, "películas vistas")
        self._lbl(102, f"{m_plays} reproducciones   •   {m_h}h  ({m_days} días)")

        self._lbl(200, str(sh_watched))
        self._lbl(201, "shows vistos")
        self._lbl(202, f"{ep_watched} episodios")
        self._lbl(203, f"{ep_plays} reproducciones   •   {ep_h}h")

        self._lbl(300, f"{total_h}h")
        self._lbl(301, f"{total_days} días en total")

        # Ratings distribution in genre/director area
        dist = rat_d.get("distribution", {})
        total_ratings = rat_d.get("total", 0)

        self._lbl(390, f"[ RATINGS  — {total_ratings} calificaciones ]")
        self._lbl(490, "")

        if total_ratings > 0 and dist:
            max_r = max((int(v) for v in dist.values()), default=1)
            row_ids = [(400, 401, 402), (410, 411, 412), (420, 421, 422),
                       (430, 431, 432), (440, 441, 442),
                       (500, 501, None), (510, 511, None), (520, 521, None),
                       (530, 531, None), (540, 541, None)]
            row = 0
            for score in range(10, 0, -1):
                count = int(dist.get(str(score), 0))
                if count == 0:
                    continue
                if row >= len(row_ids):
                    break
                ids = row_ids[row]
                self._lbl(ids[0], f"★ {score}")
                self._lbl(ids[1], _bar(count, max_r))
                if ids[2] is not None:
                    self._lbl(ids[2], str(count))
                row += 1
            # Clear remaining slots
            for ids in row_ids[row:]:
                self._lbl(ids[0], "")
                self._lbl(ids[1], "")
                if ids[2] is not None:
                    self._lbl(ids[2], "")
        else:
            for cid in (400, 401, 402, 410, 411, 412, 420, 421, 422,
                        430, 431, 432, 440, 441, 442,
                        500, 501, 510, 511, 520, 521, 530, 531, 540, 541):
                self._lbl(cid, "")

        # Storytelling narrative
        self._lbl(700, _generate_story_alltime(s))

        # Ratings extra rows (601-610)
        self._lbl(600, "")
        for i in range(601, 611):
            self._lbl(i, "")

    def onClick(self, control_id: int):
        if control_id == 2:
            self.close()

    def onAction(self, action):
        if action.getId() in ACTION_BACK:
            self.close()


def show_stats_window(stats_data: dict, period_label: str, is_all_time: bool = False):
    dialog = StatsDialog("DialogStats.xml", ADDON_PATH, "Default", "720p")
    dialog.stats_data = stats_data
    dialog.period_label = period_label
    dialog.is_all_time = is_all_time
    dialog.doModal()
    del dialog
