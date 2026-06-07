(() => {
    const state = {
        regions: [], selected: null, nextId: 1, bound: false,
        serialized: "[]", overlayVisible: false,
        overlayObserver: null, canvasPreviewVisible: false,
    };

    function root() {
        return document.getElementById("i4-builder");
    }

    function layoutInput() {
        return document.querySelector("#i4-layout-json textarea");
    }

    function save() {
        const input = layoutInput();
        if (!input) return;
        const serialized = state.regions.length ? JSON.stringify(state.regions.map(region => ({
            x: region.x,
            y: region.y,
            w: region.w,
            h: region.h,
            type: region.type,
            text: region.text || "",
            desc: region.desc || "",
            palette: paletteArray(region.palette),
            color: region.color || "#9E9E9E",
        }))) : "";
        state.serialized = serialized;
        setNativeValue(input, serialized);
    }

    function paletteArray(value) {
        if (Array.isArray(value)) return value;
        return String(value || "").replaceAll(",", " ").split(/\s+/).filter(Boolean);
    }

    function validColor(value, fallback="#9E9E9E") {
        const color = String(value || "").trim();
        return /^#[0-9a-f]{6}$/i.test(color) ? color.toUpperCase() : fallback;
    }

    function colorWithAlpha(color, alpha) {
        const hex = validColor(color).slice(1);
        const red = parseInt(hex.slice(0, 2), 16);
        const green = parseInt(hex.slice(2, 4), 16);
        const blue = parseInt(hex.slice(4, 6), 16);
        return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
    }

    function componentByLabel(label) {
        return [...document.querySelectorAll("[data-testid='block-info']")]
            .find(info => info.textContent.trim() === label)?.closest(
                ".gradio-textbox, .gradio-radio, .gradio-checkbox"
            );
    }

    function setNativeValue(input, value) {
        const prototype = input instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
        if (setter) setter.call(input, value);
        else input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function setGradioValue(elemId, label, value) {
        const root = document.getElementById(elemId) || componentByLabel(label);
        const input = root?.querySelector("textarea, input");
        if (!input) return;
        setNativeValue(input, value == null ? "" : String(value));
    }

    function setGradioRadio(elemId, label, value) {
        const root = document.getElementById(elemId) || componentByLabel(label);
        const input = [...(root?.querySelectorAll('input[type="radio"]') || [])]
            .find(option => option.value === value);
        if (input && !input.checked) input.click();
    }

    function setGradioCheckbox(elemId, label, checked) {
        const root = document.getElementById(elemId) || componentByLabel(label);
        const input = root?.querySelector('input[type="checkbox"]');
        if (input && input.checked !== checked) input.click();
    }

    function importFullCaption(caption) {
        const style = caption.style_description || {};
        const composition = caption.compositional_deconstruction || {};
        const isPhoto = Object.prototype.hasOwnProperty.call(style, "photo");
        const importedSeed = Number.isFinite(Number(caption.seed))
            ? Number(caption.seed)
            : (Number.isFinite(Number(caption.settings?.seed))
                ? Number(caption.settings.seed)
                : -1);

        setGradioCheckbox(
            "i4-use-builder", "Use visual builder for generation", true
        );
        setGradioValue(
            "i4-high-level", "High-level description",
            caption.high_level_description || ""
        );
        setGradioValue(
            "i4-background", "Background / environment",
            composition.background || ""
        );
        setGradioRadio(
            "i4-style-kind", "Style type",
            isPhoto ? "Photograph" : "Artwork"
        );
        setGradioValue(
            "i4-aesthetics", "Aesthetics", style.aesthetics || ""
        );
        setGradioValue(
            "i4-lighting", "Lighting", style.lighting || ""
        );
        setGradioValue(
            "i4-medium", "Medium",
            style.medium || (isPhoto ? "photograph" : "illustration")
        );
        setGradioValue(
            "i4-style-detail", "Camera details or art style",
            isPhoto ? (style.photo || "") : (style.art_style || "")
        );
        setGradioValue(
            "i4-overall-palette", "Overall palette",
            paletteArray(style.color_palette || style.palette).join(" ")
        );
        setGradioValue("i4-seed", "Seed (-1 = random)", importedSeed);

        return Array.isArray(composition.elements) ? composition.elements : [];
    }

    function selectedRegion() {
        return state.regions.find(region => region.id === state.selected);
    }

    function normalize(region) {
        region.x = Math.max(0, Math.min(0.96, Number(region.x) || 0));
        region.y = Math.max(0, Math.min(0.96, Number(region.y) || 0));
        region.w = Math.max(0.04, Math.min(1 - region.x, Number(region.w) || 0.04));
        region.h = Math.max(0.04, Math.min(1 - region.y, Number(region.h) || 0.04));
        region.bbox = [
            Math.round(region.y * 1000),
            Math.round(region.x * 1000),
            Math.round((region.y + region.h) * 1000),
            Math.round((region.x + region.w) * 1000),
        ];
    }

    function syncEditor() {
        const region = selectedRegion();
        const selector = document.getElementById("i4-region-select");
        const color = document.getElementById("i4-region-color");
        const type = document.getElementById("i4-region-type");
        const text = document.getElementById("i4-region-text");
        const desc = document.getElementById("i4-region-desc");
        const palette = document.getElementById("i4-region-palette");
        const bboxInputs = ["y1", "x1", "y2", "x2"].map(
            name => document.getElementById(`i4-bbox-${name}`)
        );
        const literal = document.getElementById("i4-literal-label");
        if (selector) {
            selector.innerHTML = "";
            if (!state.regions.length) {
                selector.append(new Option("No boxes", ""));
            } else {
                state.regions.forEach((item, index) => {
                    const summary = item.type === "text"
                        ? (item.text || item.desc || "Text")
                        : (item.desc || "Object");
                    selector.append(new Option(
                        `${String(index + 1).padStart(2, "0")} - ${summary.slice(0, 42)}`,
                        String(item.id)
                    ));
                });
            }
            selector.value = region ? String(region.id) : "";
            selector.disabled = !state.regions.length;
        }
        [color, type, text, desc, palette, ...bboxInputs].forEach(el => {
            if (el) el.disabled = !region;
        });
        if (!region) {
            [type, text, desc, palette, ...bboxInputs].forEach(el => {
                if (el) el.value = "";
            });
            if (color) color.value = "#9E9E9E";
            if (literal) literal.style.display = "none";
            return;
        }
        color.value = validColor(region.color);
        type.value = region.type;
        text.value = region.text || "";
        desc.value = region.desc || "";
        palette.value = paletteArray(region.palette).join(" ");
        if (literal) literal.style.display = region.type === "text" ? "" : "none";
        bboxInputs.forEach((input, index) => {
            if (input) input.value = region.bbox[index];
        });
    }

    function updateCanvasPreview() {
        const canvas = document.getElementById("i4-canvas");
        const image = outputImage();
        if (!canvas) return;
        syncAspectRatio();
        if (state.canvasPreviewVisible && image?.src) {
            if (!image.naturalWidth || !image.naturalHeight) {
                image.addEventListener("load", updateCanvasPreview, { once: true });
            }
            canvas.style.backgroundImage =
                `linear-gradient(rgba(0,0,0,.12), rgba(0,0,0,.12)), url("${image.src}")`;
            canvas.classList.add("previewing");
        } else {
            canvas.style.backgroundImage = "";
            canvas.classList.remove("previewing");
        }
    }

    function render() {
        const canvas = document.getElementById("i4-canvas");
        if (!canvas) return;
        canvas.innerHTML = "";
        state.regions.forEach((region, index) => {
            normalize(region);
            const box = document.createElement("div");
            box.className = `i4-region ${region.type} ${region.id === state.selected ? "selected" : ""}`;
            box.style.left = `${region.x * 100}%`;
            box.style.top = `${region.y * 100}%`;
            box.style.width = `${region.w * 100}%`;
            box.style.height = `${region.h * 100}%`;
            box.style.borderColor = validColor(region.color);
            box.style.backgroundColor = colorWithAlpha(region.color, 0.2);
            box.dataset.id = region.id;
            box.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><div class="i4-region-label"></div><i></i>`;
            box.querySelector(".i4-region-label").textContent =
                region.type === "text" ? (region.text || "Text") : (region.desc || "Object");
            box.addEventListener("pointerdown", startDrag);
            canvas.appendChild(box);
        });
        syncEditor();
        save();
        updateCanvasPreview();
        renderOutputOverlay();
    }

    function add(type) {
        const offset = ((state.nextId - 1) * 5) % 35;
        const region = {
            id: state.nextId++,
            type,
            x: (8 + offset) / 100,
            y: (8 + offset) / 100,
            w: 0.4,
            h: 0.32,
            text: "",
            desc: "",
            palette: [],
            color: type === "text" ? "#FF304F" : "#9E9E9E",
            bbox: [],
        };
        state.regions.push(region);
        state.selected = region.id;
        render();
    }

    function regionsAtPoint(event, canvas) {
        const bounds = canvas.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width;
        const y = (event.clientY - bounds.top) / bounds.height;
        return state.regions.filter(region =>
            x >= region.x && x <= region.x + region.w &&
            y >= region.y && y <= region.y + region.h
        );
    }

    function selectNextAtPoint(event, canvas, forcedId=null) {
        if (forcedId !== null) {
            state.selected = forcedId;
            return selectedRegion();
        }
        const candidates = regionsAtPoint(event, canvas);
        if (!candidates.length) return null;
        const selectedIndex = candidates.findIndex(
            region => region.id === state.selected
        );
        state.selected = candidates[
            selectedIndex < 0 ? 0 : (selectedIndex + 1) % candidates.length
        ].id;
        return selectedRegion();
    }

    function startDrag(event) {
        event.preventDefault();
        const box = event.currentTarget;
        const canvas = document.getElementById("i4-canvas");
        const resizing = event.target.tagName === "I";
        const region = selectNextAtPoint(
            event, canvas, resizing ? Number(box.dataset.id) : null
        );
        if (!region) return;
        const bounds = canvas.getBoundingClientRect();
        const start = { x: event.clientX, y: event.clientY, rx: region.x, ry: region.y, rw: region.w, rh: region.h };
        const selectedBox = canvas.querySelector(`[data-id="${region.id}"]`);
        canvas.setPointerCapture(event.pointerId);
        document.querySelectorAll(".i4-region").forEach(el => {
            el.classList.toggle("selected", Number(el.dataset.id) === region.id);
        });
        syncEditor();

        const move = e => {
            const dx = (e.clientX - start.x) / bounds.width;
            const dy = (e.clientY - start.y) / bounds.height;
            if (resizing) {
                region.w = start.rw + dx;
                region.h = start.rh + dy;
            } else {
                region.x = start.rx + dx;
                region.y = start.ry + dy;
            }
            normalize(region);
            if (selectedBox) {
                selectedBox.style.left = `${region.x * 100}%`;
                selectedBox.style.top = `${region.y * 100}%`;
                selectedBox.style.width = `${region.w * 100}%`;
                selectedBox.style.height = `${region.h * 100}%`;
            }
            syncEditor();
            save();
        };
        const up = () => {
            canvas.removeEventListener("pointermove", move);
            canvas.removeEventListener("pointerup", up);
            render();
        };
        canvas.addEventListener("pointermove", move);
        canvas.addEventListener("pointerup", up);
    }

    function importLayout() {
        const input = layoutInput();
        if (!input) return;
        try {
            const parsed = JSON.parse(input.value || "[]");
            if (!Array.isArray(parsed)) throw new Error("Layout must be a JSON array.");
            let regions = parsed;
            if (parsed.length === 1 && parsed[0] && typeof parsed[0] === "object" &&
                ("high_level_description" in parsed[0] ||
                 "style_description" in parsed[0] ||
                 "compositional_deconstruction" in parsed[0])) {
                regions = importFullCaption(parsed[0]);
            }
            if (!regions.length) throw new Error("The prompt contains no layout elements.");
            state.regions = regions.filter(region => region && typeof region === "object").map(region => {
                let x = Number(region.x);
                let y = Number(region.y);
                let w = Number(region.w);
                let h = Number(region.h);
                if ([x, y, w, h].some(value => !Number.isFinite(value)) &&
                    Array.isArray(region.bbox) && region.bbox.length === 4) {
                    y = Number(region.bbox[0]) / 1000;
                    x = Number(region.bbox[1]) / 1000;
                    h = (Number(region.bbox[2]) - Number(region.bbox[0])) / 1000;
                    w = (Number(region.bbox[3]) - Number(region.bbox[1])) / 1000;
                }
                if (Math.max(Math.abs(x), Math.abs(y), Math.abs(w), Math.abs(h)) > 1) {
                    x /= 100; y /= 100; w /= 100; h /= 100;
                }
                const imported = {
                    id: state.nextId++,
                    x, y, w, h,
                    type: region.type === "text" ? "text" : "obj",
                    text: String(region.text || ""),
                    desc: String(region.desc || ""),
                    palette: paletteArray(region.palette || region.color_palette),
                    color: validColor(
                        region.color || region.box_color,
                        region.type === "text" ? "#FF304F" : "#9E9E9E"
                    ),
                    bbox: [],
                };
                normalize(imported);
                return imported;
            });
            state.selected = state.regions.at(-1)?.id ?? null;
            state.serialized = input.value || "[]";
            render();
        } catch (error) {
            window.alert(`Could not import Ideogram layout: ${error.message}`);
        }
    }

    function syncAspectRatio() {
        const canvas = document.getElementById("i4-canvas");
        const widthInput = document.querySelector(
            "#i4-width input[type='number'], #i4-width input"
        );
        const heightInput = document.querySelector(
            "#i4-height input[type='number'], #i4-height input"
        );
        if (!canvas || !widthInput || !heightInput) return;
        const width = Math.max(1, Number(widthInput.value) || 1);
        const height = Math.max(1, Number(heightInput.value) || 1);
        canvas.style.aspectRatio = `${width} / ${height}`;
    }

    function outputImage() {
        const root = document.getElementById("i4-output-image");
        if (!root) return null;
        const images = [...root.querySelectorAll("img")];
        return images.find(image => {
            const bounds = image.getBoundingClientRect();
            return bounds.width > 100 && bounds.height > 100;
        }) || null;
    }

    function containedImageRect(image) {
        const bounds = image.getBoundingClientRect();
        const naturalWidth = image.naturalWidth || bounds.width;
        const naturalHeight = image.naturalHeight || bounds.height;
        const scale = Math.min(
            bounds.width / naturalWidth,
            bounds.height / naturalHeight
        );
        const width = naturalWidth * scale;
        const height = naturalHeight * scale;
        return {
            left: bounds.left + (bounds.width - width) / 2,
            top: bounds.top + (bounds.height - height) / 2,
            width,
            height,
        };
    }

    function ensureOutputOverlay() {
        const root = document.getElementById("i4-output-image");
        if (!root) return null;
        let overlay = root.querySelector(".i4-output-overlay");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.className = "i4-output-overlay";
            root.appendChild(overlay);
        }
        return overlay;
    }

    function renderOutputOverlay() {
        const root = document.getElementById("i4-output-image");
        const image = outputImage();
        const overlay = ensureOutputOverlay();
        if (!root || !overlay) return;

        overlay.classList.toggle("visible", state.overlayVisible && !!image);
        if (!state.overlayVisible || !image) return;

        const rootBounds = root.getBoundingClientRect();
        const imageBounds = containedImageRect(image);
        overlay.style.left = `${imageBounds.left - rootBounds.left}px`;
        overlay.style.top = `${imageBounds.top - rootBounds.top}px`;
        overlay.style.width = `${imageBounds.width}px`;
        overlay.style.height = `${imageBounds.height}px`;
        overlay.innerHTML = '<div class="i4-output-grid"></div>';

        state.regions.forEach((region, index) => {
            normalize(region);
            const box = document.createElement("div");
            box.className = `i4-output-box ${region.type}`;
            box.style.left = `${region.x * 100}%`;
            box.style.top = `${region.y * 100}%`;
            box.style.width = `${region.w * 100}%`;
            box.style.height = `${region.h * 100}%`;
            box.style.borderColor = validColor(region.color);
            box.style.backgroundColor = colorWithAlpha(region.color, 0.1);
            box.title = region.type === "text"
                ? (region.text || region.desc || "Text")
                : (region.desc || "Object");
            const label = document.createElement("span");
            label.textContent = String(index + 1).padStart(2, "0");
            box.appendChild(label);
            overlay.appendChild(box);
        });
    }

    function toggleOutputOverlay() {
        state.overlayVisible = !state.overlayVisible;
        const button = document.getElementById("i4-toggle-output-overlay");
        if (button) {
            button.textContent = state.overlayVisible
                ? "Hide layout overlay"
                : "Show layout overlay";
            button.setAttribute("aria-pressed", String(state.overlayVisible));
            button.classList.toggle("active", state.overlayVisible);
        }
        renderOutputOverlay();
    }

    function toggleCanvasPreview() {
        state.canvasPreviewVisible = !state.canvasPreviewVisible;
        const button = document.getElementById("i4-toggle-canvas-preview");
        if (button) {
            button.textContent = state.canvasPreviewVisible
                ? "Hide last image"
                : "Show last image";
            button.classList.toggle("active", state.canvasPreviewVisible);
        }
        updateCanvasPreview();
    }

    function bindMainSplitter() {
        const split = document.getElementById("i4-main-split");
        const divider = document.getElementById("i4-main-divider");
        if (!split || !divider || divider.dataset.bound === "true") return;
        divider.dataset.bound = "true";
        divider.addEventListener("pointerdown", event => {
            if (window.matchMedia("(max-width: 900px)").matches) return;
            event.preventDefault();
            divider.setPointerCapture(event.pointerId);
            split.classList.add("resizing");
            const bounds = split.getBoundingClientRect();
            const move = moveEvent => {
                const minimum = Math.min(360, bounds.width * 0.3);
                const dividerWidth = divider.getBoundingClientRect().width;
                const available = Math.max(1, bounds.width - dividerWidth);
                const left = Math.max(
                    minimum,
                    Math.min(available - minimum, moveEvent.clientX - bounds.left)
                );
                split.style.setProperty(
                    "--i4-left-pane-width",
                    `${left / available * 100}%`
                );
            };
            const up = () => {
                divider.removeEventListener("pointermove", move);
                divider.removeEventListener("pointerup", up);
                divider.removeEventListener("pointercancel", up);
                split.classList.remove("resizing");
            };
            divider.addEventListener("pointermove", move);
            divider.addEventListener("pointerup", up);
            divider.addEventListener("pointercancel", up);
        });
    }

    function syncInnerTabLayout() {
        const pngTab = [...document.querySelectorAll(
            "#i4-left-pane [role='tab']"
        )].find(tab => tab.textContent.trim() === "PNG Info");
        const split = document.getElementById("i4-main-split");
        if (!split || !pngTab) return;
        split.classList.toggle(
            "png-info-active",
            pngTab.getAttribute("aria-selected") === "true"
        );
    }

    async function captureFullPage() {
        const button = document.getElementById("i4-capture-page");
        if (typeof window.html2canvas !== "function") {
            window.alert("The full-page screenshot library did not load.");
            return;
        }
        const originalText = button?.textContent;
        if (button) {
            button.disabled = true;
            button.textContent = "Capturing full page...";
        }
        const ignored = [];
        try {
            await new Promise(resolve => requestAnimationFrame(
                () => requestAnimationFrame(resolve)
            ));
            const target = button.closest('[role="tabpanel"]') || root();
            if (!target) throw new Error("Could not find the Ideogram page.");
            target.querySelectorAll(".wrap").forEach(element => {
                ignored.push([
                    element,
                    element.getAttribute("data-html2canvas-ignore"),
                ]);
                element.setAttribute("data-html2canvas-ignore", "true");
            });
            const width = Math.max(target.scrollWidth, target.clientWidth);
            const height = Math.max(target.scrollHeight, target.clientHeight);
            const scale = Math.min(1, 4096 / Math.max(width, height));
            const tileHeight = Math.max(
                720,
                Math.min(1400, window.innerHeight - 80)
            );
            const tileCount = Math.ceil(height / tileHeight);
            const canvas = document.createElement("canvas");
            canvas.width = Math.max(1, Math.ceil(width * scale));
            canvas.height = Math.max(1, Math.ceil(height * scale));
            const context = canvas.getContext("2d");
            if (!context) throw new Error("Could not create screenshot canvas.");
            const tileCanvas = document.createElement("canvas");
            const background = getComputedStyle(target).backgroundColor ||
                getComputedStyle(document.body).backgroundColor;

            for (let index = 0; index < tileCount; index += 1) {
                const y = index * tileHeight;
                const currentHeight = Math.min(tileHeight, height - y);
                if (button) {
                    button.textContent =
                        `Capturing screenshot ${index + 1}/${tileCount}...`;
                }
                await new Promise(resolve => requestAnimationFrame(resolve));
                tileCanvas.width = Math.max(1, Math.ceil(width * scale));
                tileCanvas.height = Math.max(
                    1,
                    Math.ceil(currentHeight * scale)
                );
                const tileOptions = {
                    backgroundColor: background,
                    useCORS: true,
                    allowTaint: false,
                    logging: false,
                    scale,
                    canvas: tileCanvas,
                    imageTimeout: 2500,
                    removeContainer: true,
                    windowWidth: width,
                    windowHeight: currentHeight,
                    width,
                    height: currentHeight,
                    x: 0,
                    y,
                    scrollX: 0,
                    scrollY: 0,
                };
                let tile;
                try {
                    tile = await window.html2canvas(target, {
                        ...tileOptions,
                        foreignObjectRendering: true,
                    });
                } catch (fastError) {
                    console.warn(
                        "[Ideogram 4] Fast screenshot tile failed; " +
                        "using compatibility renderer.",
                        fastError
                    );
                    tileCanvas.width = Math.max(1, Math.ceil(width * scale));
                    tileCanvas.height = Math.max(
                        1,
                        Math.ceil(currentHeight * scale)
                    );
                    tile = await window.html2canvas(target, tileOptions);
                }
                context.drawImage(tile, 0, Math.round(y * scale));
            }
            const link = document.createElement("a");
            const stamp = new Date().toISOString().replaceAll(":", "-");
            link.download = `forge-full-page-${stamp}.png`;
            const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
            if (!blob) throw new Error("The browser could not encode the screenshot.");
            link.href = URL.createObjectURL(blob);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        } catch (error) {
            const detail = error instanceof Error
                ? error.message
                : String(error ?? "Unknown screenshot error");
            console.error("[Ideogram 4] Full-page screenshot failed:", error);
            window.alert(`Could not capture the Forge page: ${detail}`);
        } finally {
            ignored.forEach(([element, previous]) => {
                if (previous === null) {
                    element.removeAttribute("data-html2canvas-ignore");
                } else {
                    element.setAttribute("data-html2canvas-ignore", previous);
                }
            });
            if (button) {
                button.disabled = false;
                button.textContent = originalText;
            }
        }
    }

    function openVisualBuilderSoon() {
        let attempts = 0;
        const timer = window.setInterval(() => {
            attempts += 1;
            const visualTab = [...document.querySelectorAll('[role="tab"]')].find(
                tab => tab.textContent.trim() === "Visual JSON Builder"
            );
            if (visualTab) {
                window.clearInterval(timer);
                visualTab.click();
            } else if (attempts >= 20) {
                window.clearInterval(timer);
            }
        }, 50);
    }

    function importAfterExplicitAction() {
        const before = layoutInput()?.value;
        let attempts = 0;
        const timer = window.setInterval(() => {
            attempts += 1;
            const input = layoutInput();
            if (!input) return;
            if (input.value !== before || attempts >= 20) {
                window.clearInterval(timer);
                importLayout();
                openVisualBuilderSoon();
            }
        }, 250);
    }

    function bind() {
        if (state.bound || !root()) return;
        state.bound = true;
        document.getElementById("i4-add-object").onclick = () => add("obj");
        document.getElementById("i4-add-text").onclick = () => add("text");
        document.getElementById("i4-import-layout").onclick = importLayout;
        document.getElementById("i4-toggle-canvas-preview").onclick =
            toggleCanvasPreview;
        document.getElementById("i4-toggle-output-overlay").onclick =
            toggleOutputOverlay;
        document.getElementById("i4-capture-page").onclick = captureFullPage;
        const pngBuilderButton = document.querySelector(
            "#i4-send-png-builder button"
        ) || document.getElementById("i4-send-png-builder");
        if (pngBuilderButton) {
            pngBuilderButton.addEventListener("click", () => {
                openVisualBuilderSoon();
                importAfterExplicitAction();
            });
        }
        const previousButton = document.querySelector(
            "#i4-load-previous button"
        ) || document.getElementById("i4-load-previous");
        if (previousButton) {
            previousButton.addEventListener("click", importAfterExplicitAction);
        }
        const clearButton = document.querySelector(
            "#i4-clear-prompt button"
        ) || document.getElementById("i4-clear-prompt");
        if (clearButton) {
            clearButton.addEventListener("click", () => {
                window.setTimeout(() => {
                    state.regions = [];
                    state.selected = null;
                    render();
                }, 100);
            });
        }
        document.getElementById("i4-delete-region").onclick = () => {
            state.regions = state.regions.filter(region => region.id !== state.selected);
            state.selected = state.regions.at(-1)?.id ?? null;
            render();
        };
        ["type", "text", "desc", "palette"].forEach(name => {
            const element = document.getElementById(`i4-region-${name}`);
            element.addEventListener("input", () => {
                const region = selectedRegion();
                if (!region) return;
                region[name] = name === "palette" ? paletteArray(element.value) : element.value;
                render();
            });
        });
        document.getElementById("i4-region-color").addEventListener("input", event => {
            const region = selectedRegion();
            if (!region) return;
            region.color = validColor(event.target.value);
            render();
        });
        document.getElementById("i4-region-select").addEventListener("change", event => {
            state.selected = Number(event.target.value) || null;
            render();
        });
        ["y1", "x1", "y2", "x2"].forEach(name => {
            document.getElementById(`i4-bbox-${name}`).addEventListener("input", () => {
                const region = selectedRegion();
                if (!region) return;
                const values = ["y1", "x1", "y2", "x2"].map(key =>
                    Math.max(0, Math.min(1000, Number(
                        document.getElementById(`i4-bbox-${key}`).value
                    ) || 0))
                );
                const [y1, x1, y2, x2] = values;
                region.x = Math.min(x1, x2) / 1000;
                region.y = Math.min(y1, y2) / 1000;
                region.w = Math.max(40, Math.abs(x2 - x1)) / 1000;
                region.h = Math.max(40, Math.abs(y2 - y1)) / 1000;
                normalize(region);
                const box = document.querySelector(
                    `.i4-region[data-id="${region.id}"]`
                );
                if (box) {
                    box.style.left = `${region.x * 100}%`;
                    box.style.top = `${region.y * 100}%`;
                    box.style.width = `${region.w * 100}%`;
                    box.style.height = `${region.h * 100}%`;
                }
                save();
            });
        });
        ["i4-width", "i4-height"].forEach(id => {
            document.querySelectorAll(`#${id} input`).forEach(input => {
                input.addEventListener("input", syncAspectRatio);
                input.addEventListener("change", syncAspectRatio);
            });
        });
        syncAspectRatio();
        bindMainSplitter();
        document.querySelectorAll("#i4-left-pane [role='tab']").forEach(tab => {
            tab.addEventListener("click", () => {
                window.setTimeout(syncInnerTabLayout, 0);
            });
        });
        syncInnerTabLayout();
        render();
        window.addEventListener("resize", renderOutputOverlay);
        const outputRoot = document.getElementById("i4-output-image");
        if (outputRoot) {
            state.overlayObserver = new MutationObserver(mutations => {
                const externalChange = mutations.some(mutation => {
                    const target = mutation.target;
                    return !target.closest?.(".i4-output-overlay");
                });
                if (externalChange) renderOutputOverlay();
                if (externalChange) updateCanvasPreview();
            });
            state.overlayObserver.observe(outputRoot, {
                childList: true, subtree: true, attributes: true,
                attributeFilter: ["src", "style", "class"],
            });
            if (window.ResizeObserver) {
                new ResizeObserver(renderOutputOverlay).observe(outputRoot);
            }
        }
        window.setInterval(() => {
            if (state.overlayVisible) renderOutputOverlay();
        }, 500);
    }

    const observer = new MutationObserver(bind);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    bind();
})();
