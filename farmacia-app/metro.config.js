const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

// En web, reemplaza react-native-maps con el stub vacío
const originalResolve = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (
    platform === "web" &&
    (moduleName === "react-native-maps" ||
      moduleName.startsWith("react-native-maps/"))
  ) {
    return {
      filePath: require.resolve("./components/MapComponents.web.js"),
      type: "sourceFile",
    };
  }
  if (originalResolve) return originalResolve(context, moduleName, platform);
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
