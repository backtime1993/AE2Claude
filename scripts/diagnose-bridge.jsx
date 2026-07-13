(function () {
    try {
        var project = app.project;
        var active = project ? project.activeItem : null;
        var activeComp = null;
        if (active && active instanceof CompItem) {
            activeComp = {
                id: active.id,
                name: active.name,
                width: active.width,
                height: active.height,
                duration: active.duration,
                frameRate: active.frameRate,
                layerCount: active.numLayers
            };
        }

        return JSON.stringify({
            ok: true,
            app: {
                version: app.version,
                buildName: app.buildName,
                buildNumber: app.buildNumber,
                isoLanguage: app.isoLanguage,
                effectCount: app.effects ? app.effects.length : 0
            },
            project: project ? {
                file: project.file ? project.file.fsName : null,
                itemCount: project.numItems
            } : null,
            activeComp: activeComp
        });
    } catch (err) {
        return JSON.stringify({
            ok: false,
            error: String(err),
            line: err && err.line ? err.line : null
        });
    }
})();
