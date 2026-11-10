import UI from "./ui.js";
import keysyms from "../core/input/keysymdef.js";

const XK = { CONTROL_L: 0xffe3, CONTROL_R: 0xffe4, ALT_L: 0xffe9, SUPER_L: 0xffeb, RETURN: 0xff0d, TAB: 0xff09 };
const KEYSYM_OF_CONTROL_CHARACTER = new Map([["\n", XK.RETURN], ["\t", XK.TAB]]);
const KEYBOARD_BOX_ID = "noVNC_keyboardinput";
const LEFT_CONTROL_CODE = "ControlLeft";
const RIGHT_CONTROL_CODE = "ControlRight";
const CONTROL_KEYSYM_OF_CODE = new Map([[LEFT_CONTROL_CODE, XK.CONTROL_L], [RIGHT_CONTROL_CODE, XK.CONTROL_R]]);
const MAX_PASTED_CHARACTERS = 10000;
const IS_APPLE = /mac|iphone|ipad|ipod/i.test(navigator.platform);
let lastControlCode = LEFT_CONTROL_CODE;
let heldOnRemote = null;

const isFormField = (el) => el.matches?.("input, textarea, select") && el.id !== KEYBOARD_BOX_ID;
const isGrabbedByNoVnc = (el) => el instanceof HTMLCanvasElement || el.id === KEYBOARD_BOX_ID;
const isPasteShortcut = (e) =>
    (IS_APPLE ? e.metaKey : e.ctrlKey) && !e.altKey && !e.shiftKey && (e.key.toLowerCase() === "v" || e.code === "KeyV");

const keysymOf = (char) => KEYSYM_OF_CONTROL_CHARACTER.get(char) ?? keysyms.lookup(char.codePointAt(0));

function typeOnRemote(rfb, text, held) {
    const controlKeysym = CONTROL_KEYSYM_OF_CODE.get(held);
    if (controlKeysym) rfb.sendKey(controlKeysym, held, false);
    if (held === "Meta") {
        rfb.sendKey(XK.ALT_L, "MetaLeft", false);
        rfb.sendKey(XK.SUPER_L, "MetaRight", false);
    }
    for (const char of text.replace(/\r\n?/g, "\n")) {
        rfb.sendKey(keysymOf(char), "");
    }
    if (controlKeysym) rfb.sendKey(controlKeysym, held, true);
}

window.addEventListener("keydown", (e) => {
    if (e.key === "Control") lastControlCode = e.code === RIGHT_CONTROL_CODE ? RIGHT_CONTROL_CODE : LEFT_CONTROL_CODE;
    if (!UI.rfb || !isPasteShortcut(e) || isFormField(e.target)) return;
    e.stopPropagation();
    if (!isGrabbedByNoVnc(e.target)) return;
    heldOnRemote = IS_APPLE ? "Meta" : lastControlCode;
    e.target.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyV" }));
}, true);
window.addEventListener("keyup", (e) => {
    if (e.key === "Control" || e.key === "Meta") heldOnRemote = null;
}, true);
window.addEventListener("paste", (e) => {
    const held = heldOnRemote;
    heldOnRemote = null;
    const text = e.clipboardData?.getData("text/plain");
    if (!UI.rfb || !text || isFormField(e.target)) return;
    e.preventDefault();
    if (text.length > MAX_PASTED_CHARACTERS) {
        UI.showStatus(`Paste refused: the text has ${text.length} characters, the limit is ${MAX_PASTED_CHARACTERS}.`, "warn");
        return;
    }
    typeOnRemote(UI.rfb, text, held);
});
