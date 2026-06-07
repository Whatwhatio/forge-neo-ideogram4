# Ideogram 4 for Forge Neo

This extension adds a separate **Ideogram 4** tab to Forge Neo and runs
Ideogram's official inference package in an isolated Python environment.
Forge's own Torch and dependencies are not modified.

## Install from Git

1. Accept the gated model license:
   https://huggingface.co/ideogram-ai/ideogram-4-nf4
2. In Forge Neo, open **Extensions > Install from URL**.
3. Paste this repository's Git URL and install it.
4. Restart Forge Neo. The extension creates its isolated environment and
   installs its dependencies during startup. The first setup downloads a
   large CUDA-enabled PyTorch package and can take several minutes.
5. Either paste a Hugging Face read token into the tab or authenticate the extension
   environment:

   `env\Scripts\hf.exe auth login`

6. Open the **Ideogram 4** tab.

For a manual installation, clone this repository into Forge Neo's
`extensions` directory and restart Forge Neo:

```powershell
cd path\to\sd-webui-forge-neo\extensions
git clone https://github.com/Whatwhatio/forge-neo-ideogram4.git ideogram4_forge
```

If automatic setup fails, close Forge Neo and run `setup.bat` once.

The first generation downloads the weights to the normal Hugging Face cache
and loads the model automatically. Download, model-loading, sampling-step,
decoding, and save progress appears in both the Forge Neo console and the tab.

The blue down-arrow restores the settings from the previous generation
attempt. The trash button clears the prompt and restores builder defaults.
Settings are saved before generation begins, so they survive a failed
generation or worker crash. Hugging Face and Ideogram API tokens are never
written to this file.

**Download full-page screenshot** captures the complete Forge page without
changing browser zoom. The **PNG Info** tab reads metadata from Ideogram PNGs
and can restore their prompt, settings, and boxes into the visual builder.

## Visual JSON Builder

Open **Visual JSON Builder**, enable **Use visual builder for generation**, and
add object or text regions. Drag a box to move it and drag its lower-right
corner to resize it. The output width and height control the canvas aspect
ratio.

The layout field uses the same normalized `x`, `y`, `w`, `h` region format as
KJNodes' `Ideogram4PromptBuilderKJ`. Paste a KJNodes `elements_data` array into
the field and click **Import JSON into Visual Builder** immediately below the
JSON editor.

## Rollback

Close Forge Neo and delete this entire `ideogram4_forge` directory. No Forge
core files or Forge Python packages are changed.

## Licensing

The extension integration code should be distributed under the license chosen
by its author. The bundled `official_source` directory is Ideogram's official
inference code and is distributed under Apache License 2.0; its original
license is retained in `official_source/LICENSE.md`.

The Ideogram 4 model weights are not included in this repository. Users
download them separately from Hugging Face and must accept Ideogram's
Non-Commercial Model Agreement:
`official_source/model_licenses/LICENSE-IDEOGRAM-4-NON-COMMERCIAL`.

This is an unofficial community extension and is not endorsed by Ideogram.
