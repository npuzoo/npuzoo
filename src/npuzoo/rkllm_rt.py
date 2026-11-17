"""ctypes binding to Rockchip's RKLLM runtime (librkllmrt.so).

The C API changed shape between releases, so there are two layouts here,
each transcribed from the official rkllm.h of those releases
(airockchip/rknn-llm, rkllm-runtime/Linux/librkllm_api/include/rkllm.h):

  "1.3"  runtime 1.3.0 – 1.3.1: rkllm_init takes an RKLLMCallback struct;
         RKLLMParam has ignore_eos_token; RKLLMInferParam has per-run
         sampling parameters and max_new_tokens.
  "1.2"  runtime 1.2.1 – 1.2.3: rkllm_init takes the result callback itself;
         RKLLMParam carries img_start / img_end / img_content.

Runtimes before 1.2.1 lack role / enable_thinking in RKLLMInput and return
void from the callback; they are refused rather than guessed at.

tools/check_rkllm_abi.py compiles each official header and checks every
size and offset below against it. That is all the verification possible
without a board: this module has not yet run on real hardware.
"""
import codecs
import ctypes
import re

# ------------------------------------------------------------ shared types

CPU_BIG = (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7)      # A76 cores on RK3588 / A72 on RK3576
CPU_LITTLE = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)

RUN_NORMAL, RUN_WAITING, RUN_FINISH, RUN_ERROR = 0, 1, 2, 3
INPUT_PROMPT, INPUT_TOKEN, INPUT_EMBED, INPUT_MULTIMODAL = 0, 1, 2, 3
INFER_GENERATE = 0


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104),
    ]


_SAMPLING = [
    ("top_k", ctypes.c_int32),
    ("top_p", ctypes.c_float),
    ("temperature", ctypes.c_float),
    ("repeat_penalty", ctypes.c_float),
    ("frequency_penalty", ctypes.c_float),
    ("presence_penalty", ctypes.c_float),
    ("mirostat", ctypes.c_int32),
    ("mirostat_tau", ctypes.c_float),
    ("mirostat_eta", ctypes.c_float),
]
_PARAM_HEAD = [
    ("model_path", ctypes.c_char_p),
    ("max_context_len", ctypes.c_int32),
    ("max_new_tokens", ctypes.c_int32),
    ("top_k", ctypes.c_int32),
    ("n_keep", ctypes.c_int32),
    ("top_p", ctypes.c_float),
    ("temperature", ctypes.c_float),
    ("repeat_penalty", ctypes.c_float),
    ("frequency_penalty", ctypes.c_float),
    ("presence_penalty", ctypes.c_float),
    ("mirostat", ctypes.c_int32),
    ("mirostat_tau", ctypes.c_float),
    ("mirostat_eta", ctypes.c_float),
    ("skip_special_token", ctypes.c_bool),
]


class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [("embed", ctypes.POINTER(ctypes.c_float)), ("n_tokens", ctypes.c_size_t)]


class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [("input_ids", ctypes.POINTER(ctypes.c_int32)), ("n_tokens", ctypes.c_size_t)]


class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [("lora_adapter_name", ctypes.c_char_p)]


class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [("save_prompt_cache", ctypes.c_int), ("prompt_cache_path", ctypes.c_char_p)]


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [("hidden_states", ctypes.POINTER(ctypes.c_float)), ("embd_size", ctypes.c_int),
                ("num_tokens", ctypes.c_int)]


class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [("logits", ctypes.POINTER(ctypes.c_float)), ("vocab_size", ctypes.c_int),
                ("num_tokens", ctypes.c_int)]


class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float),
    ]


class RKLLMResult(ctypes.Structure):
    # identical in 1.2.1 – 1.3.1
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int32),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat),
    ]


LLMResultCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)
LLMTokenizerCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
                                        ctypes.POINTER(ctypes.c_int32), ctypes.c_int32)
LLMGetEmbedCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32),
                                       ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64)


# ------------------------------------------------------------ 1.3.x layout

class RKLLMParam13(ctypes.Structure):
    _fields_ = _PARAM_HEAD + [
        ("ignore_eos_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("extend_param", RKLLMExtendParam),
    ]


class _Image13(ctypes.Structure):
    _fields_ = [("image_embed", ctypes.POINTER(ctypes.c_float)), ("n_image_tokens", ctypes.c_size_t),
                ("n_image", ctypes.c_size_t), ("image_start", ctypes.c_char_p), ("image_end", ctypes.c_char_p),
                ("image_content", ctypes.c_char_p), ("image_width", ctypes.c_size_t),
                ("image_height", ctypes.c_size_t)]


class _Video13(ctypes.Structure):
    _fields_ = [("video_embed", ctypes.POINTER(ctypes.c_float)), ("n_frame_tokens", ctypes.c_size_t),
                ("n_frame_per_video", ctypes.c_size_t), ("n_video", ctypes.c_size_t),
                ("video_start", ctypes.c_char_p), ("video_end", ctypes.c_char_p),
                ("video_content", ctypes.c_char_p), ("frame_width", ctypes.c_size_t),
                ("frame_height", ctypes.c_size_t)]


class _Audio13(ctypes.Structure):
    # added in 1.3.1; harmless extra room for a 1.3.0 runtime, which reads less
    _fields_ = [("audio_embed", ctypes.POINTER(ctypes.c_float)), ("n_audio_tokens", ctypes.c_size_t),
                ("n_audio", ctypes.c_size_t), ("audio_start", ctypes.c_char_p), ("audio_end", ctypes.c_char_p),
                ("audio_content", ctypes.c_char_p)]


class RKLLMMultiModalInput13(ctypes.Structure):
    _fields_ = [("prompt", ctypes.c_char_p), ("image", _Image13), ("video", _Video13), ("audio", _Audio13)]


class _InputUnion13(ctypes.Union):
    _fields_ = [("prompt_input", ctypes.c_char_p), ("embed_input", RKLLMEmbedInput),
                ("token_input", RKLLMTokenInput), ("multimodal_input", RKLLMMultiModalInput13)]


class RKLLMInput13(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("role", ctypes.c_char_p), ("enable_thinking", ctypes.c_bool), ("input_type", ctypes.c_int),
                ("u", _InputUnion13)]


class RKLLMSamplingParam(ctypes.Structure):
    _fields_ = list(_SAMPLING)


class RKLLMInferParam13(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("sampling_params", ctypes.POINTER(RKLLMSamplingParam)),
        ("keep_history", ctypes.c_int),
        ("max_new_tokens", ctypes.c_int32),
    ]


class RKLLMCallback(ctypes.Structure):
    _fields_ = [
        ("result_callback", LLMResultCallback),
        ("result_userdata", ctypes.c_void_p),
        ("tokenizer_callback", LLMTokenizerCallback),
        ("tokenizer_userdata", ctypes.c_void_p),
        ("embed_callback", LLMGetEmbedCallback),
        ("embed_userdata", ctypes.c_void_p),
    ]


# ------------------------------------------------------------ 1.2.1 – 1.2.3 layout

class RKLLMParam12(ctypes.Structure):
    _fields_ = _PARAM_HEAD + [
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMMultiModalInput12(ctypes.Structure):
    _fields_ = [("prompt", ctypes.c_char_p), ("image_embed", ctypes.POINTER(ctypes.c_float)),
                ("n_image_tokens", ctypes.c_size_t), ("n_image", ctypes.c_size_t),
                ("image_width", ctypes.c_size_t), ("image_height", ctypes.c_size_t)]


class _InputUnion12(ctypes.Union):
    _fields_ = [("prompt_input", ctypes.c_char_p), ("embed_input", RKLLMEmbedInput),
                ("token_input", RKLLMTokenInput), ("multimodal_input", RKLLMMultiModalInput12)]


class RKLLMInput12(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("role", ctypes.c_char_p), ("enable_thinking", ctypes.c_bool), ("input_type", ctypes.c_int),
                ("u", _InputUnion12)]


class RKLLMInferParam12(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("keep_history", ctypes.c_int),
    ]


PROFILES = {
    "1.3": {"param": RKLLMParam13, "input": RKLLMInput13, "infer": RKLLMInferParam13, "callback_struct": True},
    "1.2": {"param": RKLLMParam12, "input": RKLLMInput12, "infer": RKLLMInferParam12, "callback_struct": False},
}


def profile_for(version):
    """ABI profile name for a runtime version string, or None if unsupported."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if not m:
        return None
    v = tuple(int(x) for x in m.groups())
    if (1, 3, 0) <= v < (1, 4, 0):
        return "1.3"
    if (1, 2, 1) <= v < (1, 3, 0):
        return "1.2"
    return None


class RuntimeError_(Exception):
    """Something the runtime refused; message says what to do."""


# ------------------------------------------------------------ session

class Session(object):
    """One model loaded on the NPU.

    lib is a loaded CDLL (or a stand-in with the same functions, in tests);
    profile is "1.3" or "1.2".
    """

    def __init__(self, lib, profile, model_path, max_context_len=4096, max_new_tokens=1024,
                 top_k=1, top_p=0.9, temperature=0.8, repeat_penalty=1.1, cpus_mask=CPU_BIG, cpus_num=4,
                 embed_flash=1, ignore_eos=False):
        if profile not in PROFILES:
            raise RuntimeError_("unsupported runtime layout %r" % profile)
        self.lib, self.profile = lib, profile
        P = PROFILES[profile]
        self._P = P
        self._chunks, self._decoder = [], None
        self._state, self._perf, self._on_text = None, None, None

        lib.rkllm_createDefaultParam.restype = P["param"]
        param = lib.rkllm_createDefaultParam()
        self._model_path = model_path.encode("utf-8")
        param.model_path = self._model_path
        param.max_context_len = int(max_context_len)
        param.max_new_tokens = int(max_new_tokens)
        param.top_k, param.top_p, param.temperature = int(top_k), float(top_p), float(temperature)
        param.repeat_penalty = float(repeat_penalty)
        param.skip_special_token = True
        if ignore_eos and "ignore_eos_token" in dict(P["param"]._fields_):
            param.ignore_eos_token = True      # 1.3+: fixed-length output, for benchmarks
        param.is_async = False
        param.n_keep = -1
        param.extend_param.base_domain_id = 0
        param.extend_param.embed_flash = int(embed_flash)
        param.extend_param.n_batch = 1
        param.extend_param.use_cross_attn = 0
        param.extend_param.enabled_cpus_num = int(cpus_num)
        param.extend_param.enabled_cpus_mask = int(cpus_mask)
        self._param = param

        self._cb = LLMResultCallback(self._callback)      # keep a reference: the C side holds the pointer
        self.handle = ctypes.c_void_p()
        lib.rkllm_init.restype = ctypes.c_int
        if P["callback_struct"]:
            cbs = RKLLMCallback()
            cbs.result_callback = self._cb
            self._cbs = cbs
            lib.rkllm_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(P["param"]),
                                       ctypes.POINTER(RKLLMCallback)]
            ret = lib.rkllm_init(ctypes.byref(self.handle), ctypes.byref(param), ctypes.byref(cbs))
        else:
            lib.rkllm_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(P["param"]),
                                       LLMResultCallback]
            ret = lib.rkllm_init(ctypes.byref(self.handle), ctypes.byref(param), self._cb)
        if ret != 0:
            raise RuntimeError_("rkllm_init returned %s. Run the same model through `npuzoo inspect`, and pipe "
                                "the runtime's log through `npuzoo explain`." % ret)

        lib.rkllm_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(P["input"]), ctypes.POINTER(P["infer"]),
                                  ctypes.c_void_p]
        lib.rkllm_run.restype = ctypes.c_int

    # the runtime calls this from inside rkllm_run, on the same thread
    def _callback(self, result, userdata, state):
        try:
            if state == RUN_NORMAL and result and result.contents.text:
                piece = self._decoder.decode(result.contents.text)
                if piece:
                    self._chunks.append(piece)
                    if self._on_text:
                        self._on_text(piece)
            elif state == RUN_FINISH:
                self._state = RUN_FINISH
                if result:
                    p = result.contents.perf
                    self._perf = {
                        "prefill_ms": round(p.prefill_time_ms, 2), "prefill_tokens": p.prefill_tokens,
                        "generate_ms": round(p.generate_time_ms, 2), "generate_tokens": p.generate_tokens,
                        "memory_mb": round(p.memory_usage_mb, 1),
                    }
            elif state == RUN_ERROR:
                self._state = RUN_ERROR
        except Exception:
            # never let a Python exception unwind into C
            self._state = RUN_ERROR
        return 0

    def generate(self, prompt, role="user", enable_thinking=False, keep_history=False,
                 max_new_tokens=None, on_text=None):
        """Run one turn. Returns {"text", "perf", "finished"}."""
        P = self._P
        inp = P["input"]()
        self._role = (role or "user").encode("utf-8")
        self._prompt = prompt.encode("utf-8")
        inp.role = self._role
        inp.enable_thinking = bool(enable_thinking)
        inp.input_type = INPUT_PROMPT
        inp.prompt_input = self._prompt

        infer = P["infer"]()
        infer.mode = INFER_GENERATE
        infer.keep_history = 1 if keep_history else 0
        if max_new_tokens and "max_new_tokens" in dict(P["infer"]._fields_):
            infer.max_new_tokens = int(max_new_tokens)

        self._chunks, self._state, self._perf = [], None, None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._on_text = on_text
        ret = self.lib.rkllm_run(self.handle, ctypes.byref(inp), ctypes.byref(infer), None)
        tail = self._decoder.decode(b"", final=True)
        if tail:
            self._chunks.append(tail)
            if on_text:
                on_text(tail)
        if ret != 0 or self._state == RUN_ERROR:
            raise RuntimeError_("rkllm_run failed (returned %s). Pipe the runtime's log through "
                                "`npuzoo explain`." % ret)
        return {"text": "".join(self._chunks), "perf": self._perf, "finished": self._state == RUN_FINISH}

    def clear_history(self, keep_system_prompt=True):
        fn = self.lib.rkllm_clear_kv_cache
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        fn.restype = ctypes.c_int
        return fn(self.handle, 1 if keep_system_prompt else 0, None, None)

    def set_chat_template(self, system_prompt, prefix, postfix):
        fn = self.lib.rkllm_set_chat_template
        fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        fn.restype = ctypes.c_int
        return fn(self.handle, system_prompt.encode("utf-8"), prefix.encode("utf-8"), postfix.encode("utf-8"))

    def abort(self):
        self.lib.rkllm_abort.argtypes = [ctypes.c_void_p]
        return self.lib.rkllm_abort(self.handle)

    def close(self):
        if self.handle:
            self.lib.rkllm_destroy.argtypes = [ctypes.c_void_p]
            self.lib.rkllm_destroy(self.handle)
            self.handle = ctypes.c_void_p()


def tokens_per_second(perf):
    """(prefill tok/s, generate tok/s) from the runtime's own counters."""
    if not perf:
        return None, None

    def rate(tokens, ms):
        return round(tokens * 1000.0 / ms, 2) if ms and tokens else None
    return rate(perf["prefill_tokens"], perf["prefill_ms"]), rate(perf["generate_tokens"], perf["generate_ms"])
