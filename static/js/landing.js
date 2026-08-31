document.addEventListener("DOMContentLoaded", function () {
    const page = document.querySelector("[data-public-home]");

    if (!page) {
        return;
    }

    const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;
    const header = document.querySelector(".public-header");
    const radar = page.querySelector("[data-public-radar]");
    const radarOrigin = radar
        ? radar.querySelector(".public-radar-origin")
        : null;
    const radarBlipLayer = radar
        ? radar.querySelector("[data-public-radar-blips]")
        : null;
    const radarThemeWave = radar
        ? radar.querySelector("[data-public-radar-theme-wave]")
        : null;
    const themeCurtain = page.querySelector("[data-public-theme-curtain]");
    const documentRoot = document.documentElement;
    const baseToggleTheme = window.toggleTheme;
    const setPageTheme = window.applyTheme;
    const radarSweepDuration = 12000;
    const radarStartedAt = window.performance.now();
    const radarTimers = [];
    let radarBlips = [];
    let radarResizeTimer = 0;
    let themeTransitionRunning = false;

    const radarJobs = [
        "Platform Engineer",
        "SRE - Remote",
        "Cloud Security Engineer",
        "Backend Engineer",
        "DevOps Engineer",
    ];
    const radarPositions = [
        [12, 22],
        [84, 18],
        [18, 64],
        [76, 72],
        [91, 48],
        [34, 18],
        [65, 29],
        [7, 43],
        [55, 78],
        [28, 82],
        [71, 10],
        [44, 60],
        [88, 84],
        [22, 36],
    ];

    function getRadarCenter() {
        if (!radarOrigin) {
            return {
                x: window.innerWidth / 2,
                y: Math.min(window.innerHeight * 0.43 + 68, 498),
            };
        }

        const originRect = radarOrigin.getBoundingClientRect();

        return {
            x: originRect.left + originRect.width / 2,
            y: originRect.top + originRect.height / 2,
        };
    }

    function updateRadarBlipAngles() {
        const center = getRadarCenter();

        radarBlips.forEach(function (blip) {
            const rect = blip.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            const angle = (
                Math.atan2(x - center.x, center.y - y) * 180 / Math.PI
                + 360
            ) % 360;

            blip.dataset.radarAngle = angle.toFixed(2);
        });
    }

    function activateRadarBlip(blip, className, duration) {
        if (!blip || reduceMotion || document.hidden) {
            return;
        }

        const activeClass = className || "is-detected";
        blip.classList.remove(activeClass);
        void blip.offsetWidth;
        blip.classList.add(activeClass);

        window.setTimeout(function () {
            blip.classList.remove(activeClass);
        }, duration || 900);
    }

    function createRadarBlips() {
        if (!radarBlipLayer) {
            return;
        }

        radarPositions.forEach(function (position, index) {
            const blip = document.createElement("span");
            const jobLabel = radarJobs[index] || "";

            blip.className = "public-radar-blip";
            blip.style.setProperty("--radar-blip-x", position[0] + "%");
            blip.style.setProperty("--radar-blip-y", position[1] + "%");

            if (position[0] > 70) {
                blip.classList.add("is-label-left");
            }

            if (jobLabel) {
                const label = document.createElement("small");
                label.className = "public-radar-blip-label";
                label.textContent = jobLabel;
                blip.appendChild(label);
            }

            radarBlipLayer.appendChild(blip);
        });

        radarBlips = Array.from(
            radarBlipLayer.querySelectorAll(".public-radar-blip")
        );
        window.requestAnimationFrame(updateRadarBlipAngles);
    }

    function scanRadarBlips() {
        if (reduceMotion || document.hidden || !radarBlips.length) {
            return;
        }

        const now = window.performance.now();
        const sweepAngle = (
            (now - radarStartedAt) % radarSweepDuration
        ) / radarSweepDuration * 360;

        radarBlips.forEach(function (blip) {
            const blipAngle = Number(blip.dataset.radarAngle || 0);
            const angularDistance = Math.abs(
                ((blipAngle - sweepAngle + 540) % 360) - 180
            );
            const lastDetection = Number(blip.dataset.lastDetection || 0);

            if (angularDistance < 3.5 && now - lastDetection > 2400) {
                blip.dataset.lastDetection = String(now);
                activateRadarBlip(blip);
            }
        });
    }

    function activateRandomRadarBlip() {
        if (!radarBlips.length || document.hidden) {
            return;
        }

        const index = Math.floor(Math.random() * radarBlips.length);
        activateRadarBlip(radarBlips[index]);
    }

    function moveQuietRadarBlip() {
        if (reduceMotion || document.hidden || radarBlips.length <= radarJobs.length) {
            return;
        }

        const movableBlips = radarBlips.slice(radarJobs.length);
        const blip = movableBlips[Math.floor(Math.random() * movableBlips.length)];
        let x = 8 + Math.random() * 84;
        let y = 10 + Math.random() * 78;

        if (Math.abs(x - 50) < 13 && Math.abs(y - 44) < 16) {
            x += x < 50 ? -14 : 14;
            y += y < 44 ? -12 : 12;
        }

        blip.style.setProperty("--radar-blip-x", Math.max(6, Math.min(94, x)) + "%");
        blip.style.setProperty("--radar-blip-y", Math.max(8, Math.min(90, y)) + "%");
        window.setTimeout(updateRadarBlipAngles, 1250);
    }

    function pulseThemeBlips(center, radius) {
        radarBlips
            .map(function (blip) {
                const rect = blip.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;

                return {
                    blip: blip,
                    distance: Math.hypot(x - center.x, y - center.y),
                    visible: rect.width > 0 && rect.height > 0,
                };
            })
            .filter(function (entry) {
                return entry.visible;
            })
            .sort(function (a, b) {
                return a.distance - b.distance;
            })
            .filter(function (entry, index) {
                return index % 2 === 0;
            })
            .slice(0, 7)
            .forEach(function (entry) {
                const delay = Math.round(entry.distance / radius * 680);
                const timer = window.setTimeout(function () {
                    activateRadarBlip(
                        entry.blip,
                        "is-pulse-detected",
                        780
                    );
                }, delay);

                radarTimers.push(timer);
            });
    }

    function beginRadarThemePulse(center, radius) {
        documentRoot.style.setProperty("--public-theme-x", center.x + "px");
        documentRoot.style.setProperty("--public-theme-y", center.y + "px");
        documentRoot.style.setProperty("--public-theme-radius", radius + "px");
        documentRoot.style.setProperty(
            "--public-theme-wave-scale",
            String(Math.max(62, radius / 19))
        );

        page.classList.remove("is-theme-pulsing");

        if (radarThemeWave) {
            void radarThemeWave.offsetWidth;
        }

        page.classList.add("is-theme-pulsing");
        pulseThemeBlips(center, radius);
    }

    function finishRadarThemePulse() {
        page.classList.remove("is-theme-pulsing");
        documentRoot.classList.remove("public-radar-view-transition");
        themeTransitionRunning = false;
    }

    function applyRequestedTheme(theme) {
        if (typeof setPageTheme === "function") {
            setPageTheme(theme);
            return;
        }

        if (typeof baseToggleTheme === "function") {
            baseToggleTheme();
        }
    }

    function runFallbackThemeTransition(nextTheme, center, radius) {
        if (!themeCurtain || typeof themeCurtain.animate !== "function") {
            applyRequestedTheme(nextTheme);
            window.setTimeout(finishRadarThemePulse, 500);
            return;
        }

        themeCurtain.style.display = "block";
        themeCurtain.style.background = nextTheme === "theme-dark"
            ? "#06101c"
            : "#f7f9fc";

        const reveal = themeCurtain.animate(
            [
                {
                    clipPath: "circle(0 at " + center.x + "px " + center.y + "px)",
                    opacity: 1,
                },
                {
                    clipPath: "circle(" + radius + "px at " + center.x + "px " + center.y + "px)",
                    opacity: 1,
                },
            ],
            {
                duration: 720,
                easing: "cubic-bezier(0.2, 0.75, 0.2, 1)",
                fill: "forwards",
            }
        );

        reveal.finished.then(function () {
            applyRequestedTheme(nextTheme);

            return themeCurtain.animate(
                [{opacity: 1}, {opacity: 0}],
                {duration: 180, easing: "ease-out", fill: "forwards"}
            ).finished;
        }).then(function () {
            themeCurtain.getAnimations().forEach(function (animation) {
                animation.cancel();
            });
            themeCurtain.removeAttribute("style");
            finishRadarThemePulse();
        }, function () {
            applyRequestedTheme(nextTheme);
            themeCurtain.removeAttribute("style");
            finishRadarThemePulse();
        });
    }

    function togglePublicTheme() {
        if (themeTransitionRunning) {
            return;
        }

        const isDark = document.body.classList.contains("theme-dark");
        const nextTheme = isDark ? "theme-light" : "theme-dark";

        if (reduceMotion) {
            applyRequestedTheme(nextTheme);
            return;
        }

        const center = getRadarCenter();
        const radius = Math.ceil(Math.hypot(
            Math.max(center.x, window.innerWidth - center.x),
            Math.max(center.y, window.innerHeight - center.y)
        )) + 48;

        themeTransitionRunning = true;
        beginRadarThemePulse(center, radius);

        if (typeof document.startViewTransition === "function") {
            documentRoot.classList.add("public-radar-view-transition");

            const transition = document.startViewTransition(function () {
                applyRequestedTheme(nextTheme);
            });

            transition.finished.then(
                finishRadarThemePulse,
                finishRadarThemePulse
            );
            return;
        }

        runFallbackThemeTransition(nextTheme, center, radius);
    }

    createRadarBlips();

    if (!reduceMotion && radarBlips.length) {
        radarTimers.push(window.setInterval(scanRadarBlips, 120));
        radarTimers.push(window.setInterval(activateRandomRadarBlip, 3100));
        radarTimers.push(window.setInterval(moveQuietRadarBlip, 11800));

        window.addEventListener("resize", function () {
            window.clearTimeout(radarResizeTimer);
            radarResizeTimer = window.setTimeout(updateRadarBlipAngles, 180);
        }, {passive: true});
    }

    if (radar) {
        window.addEventListener("pagehide", function () {
            radarTimers.forEach(function (timer) {
                window.clearTimeout(timer);
            });
            window.clearTimeout(radarResizeTimer);
        });

        window.toggleTheme = togglePublicTheme;
    }

    function updateHeaderState() {
        if (header) {
            header.classList.toggle("is-scrolled", window.scrollY > 12);
        }
    }

    updateHeaderState();
    window.addEventListener("scroll", updateHeaderState, {passive: true});

    const revealItems = Array.from(
        page.querySelectorAll("[data-public-reveal]")
    );

    if (radar) {
        page.querySelectorAll(
            ".public-hero, .story-inner, .public-final-cta"
        ).forEach(function (group) {
            group.querySelectorAll("[data-public-reveal]").forEach(
                function (item, index) {
                    item.style.setProperty(
                        "--public-reveal-delay",
                        Math.min(index * 70, 140) + "ms"
                    );
                }
            );
        });
    }

    page.classList.add("public-motion-ready");

    if (reduceMotion || !("IntersectionObserver" in window)) {
        revealItems.forEach(function (item) {
            item.classList.add("is-visible");
        });
    } else {
        const revealObserver = new IntersectionObserver(
            function (entries, observer) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) {
                        return;
                    }

                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                });
            },
            {
                rootMargin: "0px 0px -7% 0px",
                threshold: 0.12,
            }
        );

        revealItems.forEach(function (item) {
            revealObserver.observe(item);
        });
    }

    const activityTargets = Array.from(
        page.querySelectorAll(
            "[data-live-search-demo], [data-discovery-demo], [data-pipeline-demo]"
        )
    );

    if ("IntersectionObserver" in window) {
        const activityObserver = new IntersectionObserver(
            function (entries) {
                entries.forEach(function (entry) {
                    entry.target.dataset.publicVisible = entry.isIntersecting
                        ? "true"
                        : "false";
                });
            },
            {threshold: 0.08}
        );

        activityTargets.forEach(function (target) {
            target.dataset.publicVisible = "false";
            activityObserver.observe(target);
        });
    } else {
        activityTargets.forEach(function (target) {
            target.dataset.publicVisible = "true";
        });
    }

    function canAnimate(element) {
        return (
            !reduceMotion
            && !document.hidden
            && element
            && element.dataset.publicVisible !== "false"
        );
    }

    const liveDemo = page.querySelector("[data-live-search-demo]");

    if (liveDemo) {
        const liveRoles = [
            {
                source: "Greenhouse",
                role: "Cloud Security Engineer",
                meta: "Remote | Full-time",
                age: "Posted 2h ago",
                match: 91,
                skills: [
                    ["Python", "Matched"],
                    ["AWS", "Matched"],
                    ["Docker", "Matched"],
                    ["CI/CD", "Matched"],
                    ["Kubernetes", "Partial"],
                ],
            },
            {
                source: "Lever",
                role: "DevSecOps Engineer",
                meta: "United States | Full-time",
                age: "Posted 4h ago",
                match: 87,
                skills: [
                    ["Terraform", "Matched"],
                    ["AWS", "Matched"],
                    ["CI/CD", "Matched"],
                    ["Docker", "Matched"],
                    ["Python", "Partial"],
                ],
            },
            {
                source: "Ashby",
                role: "Python Backend Engineer",
                meta: "Atlanta, GA | Full-time",
                age: "Posted 6h ago",
                match: 84,
                skills: [
                    ["Python", "Matched"],
                    ["Flask", "Matched"],
                    ["PostgreSQL", "Matched"],
                    ["Docker", "Matched"],
                    ["AWS", "Partial"],
                ],
            },
            {
                source: "Company ATS",
                role: "Security Automation Engineer",
                meta: "Remote | Full-time",
                age: "Posted 1h ago",
                match: 93,
                skills: [
                    ["Python", "Matched"],
                    ["SIEM", "Matched"],
                    ["APIs", "Matched"],
                    ["Linux", "Matched"],
                    ["Terraform", "Partial"],
                ],
            },
            {
                source: "Greenhouse",
                role: "Site Reliability Engineer",
                meta: "United States | Full-time",
                age: "Posted 3h ago",
                match: 89,
                skills: [
                    ["Linux", "Matched"],
                    ["Kubernetes", "Matched"],
                    ["Observability", "Matched"],
                    ["Terraform", "Matched"],
                    ["Go", "Partial"],
                ],
            },
        ];
        const liveStates = [
            {
                label: "Scanning job sources...",
                result: "Scanning",
                next: "Search in progress",
                progress: 8,
                activity: "Source scan started",
            },
            {
                label: "3 new positions found",
                result: "Position found",
                next: "Analyze requirements",
                progress: 14,
                activity: "Job discovered",
            },
            {
                label: "Analyzing requirements...",
                result: "Analyzing",
                next: "Compare profile",
                progress: 42,
                activity: "Requirements analyzed",
            },
            {
                label: "Profile match calculated",
                result: "Strong match",
                next: "Review match",
                progress: null,
                activity: "Profile match calculated",
            },
            {
                label: "Added to review",
                result: "Review ready",
                next: "Open review queue",
                progress: null,
                activity: "Added to review",
            },
        ];
        const roleElement = liveDemo.querySelector("[data-live-role]");
        const metaElement = liveDemo.querySelector("[data-live-meta]");
        const ageElement = liveDemo.querySelector("[data-live-age]");
        const matchElement = liveDemo.querySelector("[data-live-match]");
        const matchNote = liveDemo.querySelector("[data-live-match-note]");
        const statusElement = liveDemo.querySelector("[data-live-status]");
        const resultState = liveDemo.querySelector("[data-live-result-state]");
        const nextAction = liveDemo.querySelector("[data-live-next-action]");
        const resultPanel = liveDemo.querySelector("[data-live-content]");
        const progress = liveDemo.querySelector("[data-live-progress]");
        const progressFill = liveDemo.querySelector("[data-live-progress-fill]");
        const sources = Array.from(
            liveDemo.querySelectorAll("[data-live-source]")
        );
        const activityRows = Array.from(
            liveDemo.querySelectorAll("[data-live-activity-row]")
        );
        const activityTimes = Array.from(
            liveDemo.querySelectorAll("[data-live-activity-time]")
        );
        const activityTexts = Array.from(
            liveDemo.querySelectorAll("[data-live-activity-text]")
        );
        let activityHistory = [
            "Search profile loaded",
            "Supported sources connected",
            "Source scan started",
        ];
        let roleIndex = 0;
        let stateIndex = 0;

        function applyRole(role, animate) {
            function updateRole() {
                roleElement.textContent = role.role;
                metaElement.textContent = role.meta;
                ageElement.textContent = role.age;
                matchElement.textContent = role.match + "%";
                matchNote.textContent = "4/5 core skills matched";

                role.skills.forEach(function (skill, index) {
                    const name = liveDemo.querySelector(
                        '[data-live-skill-name="' + index + '"]'
                    );
                    const state = liveDemo.querySelector(
                        '[data-live-skill-state="' + index + '"]'
                    );

                    if (name) {
                        name.textContent = skill[0];
                    }

                    if (state) {
                        state.textContent = skill[1];
                        state.classList.toggle("is-partial", skill[1] === "Partial");
                    }
                });

                sources.forEach(function (source) {
                    const isActive = source.dataset.liveSource === role.source;
                    const sourceLabel = source.querySelector("small");
                    source.classList.toggle("is-active", isActive);

                    if (sourceLabel) {
                        sourceLabel.textContent = isActive ? "Scanning" : "Ready";
                    }
                });
            }

            if (!animate || !resultPanel) {
                updateRole();
                return;
            }

            resultPanel.classList.add("is-updating");
            window.setTimeout(function () {
                updateRole();
                resultPanel.classList.remove("is-updating");
            }, 240);
        }

        function renderActivity(message) {
            activityHistory.push(message);
            activityHistory = activityHistory.slice(-3);

            activityRows.forEach(function (row) {
                row.classList.add("is-refreshing");
            });

            window.setTimeout(function () {
                activityHistory.forEach(function (entry, index) {
                    const age = activityHistory.length - index - 1;

                    activityTexts[index].textContent = entry;
                    activityTimes[index].textContent = age === 0
                        ? "just now"
                        : age + "s ago";
                    activityRows[index].classList.toggle(
                        "is-current",
                        index === activityHistory.length - 1
                    );
                    activityRows[index].classList.remove("is-refreshing");
                });
            }, reduceMotion ? 0 : 180);
        }

        function applyLiveState(state, recordActivity) {
            const role = liveRoles[roleIndex];
            const progressValue = state.progress === null
                ? role.match
                : state.progress;

            statusElement.textContent = state.label;
            resultState.textContent = state.result;
            nextAction.textContent = state.next;
            progressFill.style.width = progressValue + "%";
            progress.setAttribute("aria-valuenow", String(progressValue));

            if (recordActivity) {
                renderActivity(state.activity);
            }
        }

        function advanceLiveDemo() {
            if (!canAnimate(liveDemo)) {
                window.setTimeout(advanceLiveDemo, 1200);
                return;
            }

            stateIndex += 1;

            if (stateIndex >= liveStates.length) {
                stateIndex = 0;
                roleIndex = (roleIndex + 1) % liveRoles.length;
                applyRole(liveRoles[roleIndex], true);
            }

            applyLiveState(liveStates[stateIndex], true);
            window.setTimeout(advanceLiveDemo, 3900);
        }

        applyRole(liveRoles[0], false);

        if (reduceMotion) {
            stateIndex = 3;
            applyLiveState(liveStates[stateIndex], false);
        } else {
            applyLiveState(liveStates[0], false);
            window.setTimeout(advanceLiveDemo, 3900);
        }
    }

    const discoveryDemo = page.querySelector("[data-discovery-demo]");

    if (discoveryDemo && !reduceMotion) {
        const discoverySources = Array.from(
            discoveryDemo.querySelectorAll("[data-discovery-source]")
        );
        const discoveryStatus = discoveryDemo.querySelector(
            "[data-discovery-status]"
        );
        const discoveryRow = discoveryDemo.querySelector(
            "[data-discovery-new-row]"
        );
        const discoveryRole = discoveryDemo.querySelector(
            "[data-discovery-role]"
        );
        const discoveryScore = discoveryDemo.querySelector(
            "[data-discovery-score]"
        );
        const discoveryJobs = [
            ["Cloud Security Engineer", "94%"],
            ["Platform Security Engineer", "90%"],
            ["Junior DevOps Engineer", "86%"],
            ["Security Operations Engineer", "92%"],
        ];
        let discoveryIndex = 0;

        function advanceDiscoveryDemo() {
            if (!canAnimate(discoveryDemo)) {
                window.setTimeout(advanceDiscoveryDemo, 1400);
                return;
            }

            discoveryIndex = (discoveryIndex + 1) % discoverySources.length;

            discoverySources.forEach(function (source, index) {
                source.classList.toggle("is-active", index === discoveryIndex);
            });

            discoveryStatus.textContent =
                "Checking " + discoverySources[discoveryIndex].textContent.trim();
            discoveryRow.classList.add("is-entering");

            window.setTimeout(function () {
                discoveryRole.textContent = discoveryJobs[discoveryIndex][0];
                discoveryScore.textContent = discoveryJobs[discoveryIndex][1];
                discoveryRow.classList.remove("is-entering");
            }, 260);

            window.setTimeout(advanceDiscoveryDemo, 5800);
        }

        window.setTimeout(advanceDiscoveryDemo, 5800);
    }

    const pipelineDemo = page.querySelector("[data-pipeline-demo]");

    if (pipelineDemo && !reduceMotion) {
        const stageOrder = ["discovered", "review", "ready", "applied"];
        const stageCounts = {
            discovered: 46,
            review: 12,
            ready: 5,
            applied: 31,
        };
        const stageMessages = {
            discovered: "Security Automation Engineer discovered",
            review: "Security Automation Engineer moved to Review",
            ready: "Saved answers verified; moved to Ready",
            applied: "Supported application recorded as Applied",
        };
        const stages = Array.from(
            pipelineDemo.querySelectorAll("[data-pipeline-stage]")
        );
        const movingJob = pipelineDemo.querySelector("[data-pipeline-mover]");
        const pipelineMessage = pipelineDemo.querySelector(
            "[data-pipeline-message]"
        );
        let pipelineIndex = 0;

        function renderPipelineCounts(activeStage) {
            stageOrder.forEach(function (stageName) {
                const count = pipelineDemo.querySelector(
                    '[data-pipeline-count="' + stageName + '"]'
                );

                if (count) {
                    count.textContent = String(
                        stageCounts[stageName] + (stageName === activeStage ? 1 : 0)
                    );
                }
            });
        }

        function advancePipelineDemo() {
            if (!canAnimate(pipelineDemo)) {
                window.setTimeout(advancePipelineDemo, 1500);
                return;
            }

            pipelineIndex = (pipelineIndex + 1) % stageOrder.length;
            const nextStageName = stageOrder[pipelineIndex];
            const nextStage = pipelineDemo.querySelector(
                '[data-pipeline-stage="' + nextStageName + '"]'
            );
            const nextList = nextStage.querySelector(".pipeline-items");

            movingJob.classList.add("is-moving");

            window.setTimeout(function () {
                nextList.appendChild(movingJob);
                stages.forEach(function (stage) {
                    stage.classList.toggle(
                        "is-active",
                        stage.dataset.pipelineStage === nextStageName
                    );
                });
                pipelineMessage.textContent = stageMessages[nextStageName];
                renderPipelineCounts(nextStageName);

                window.requestAnimationFrame(function () {
                    movingJob.classList.remove("is-moving");
                });
            }, 280);

            window.setTimeout(advancePipelineDemo, 7200);
        }

        renderPipelineCounts("discovered");
        window.setTimeout(advancePipelineDemo, 7200);
    }
});
