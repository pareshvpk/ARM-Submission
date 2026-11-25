package org.ps3.sentinel.ml

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Parity test for F2: ModelStore phone names must match model_files.json.
 */
class ModelFilesTest {

    private fun readModelFilesJson(): JSONObject {
        val candidates = listOf(
            File("../../../sentinel/data/model_files.json"),
            File("../../sentinel/data/model_files.json"),
            File("../sentinel/data/model_files.json"),
            File("sentinel/data/model_files.json")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw AssertionError("sentinel/data/model_files.json not found on the test classpath")
        return JSONObject(file.readText())
    }

    private fun readModelFilesText(): String {
        val candidates = listOf(
            File("../../../sentinel/data/model_files.json"),
            File("../../sentinel/data/model_files.json"),
            File("../sentinel/data/model_files.json"),
            File("sentinel/data/model_files.json")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw AssertionError("sentinel/data/model_files.json not found on the test classpath")
        return file.readText()
    }

    @Test
    fun testModelStoreFileNamesMatchModelFilesJson() {
        val files = readModelFilesJson().getJSONObject("files")

        val dir = File(System.getProperty("java.io.tmpdir"), "modelfiles-${System.nanoTime()}")
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        val store = ModelStore(dir, dir, ModelFileNames.defaults(), null, emptyMap())

        assertEquals(
            "url_model phone name must match model_files.json",
            files.getJSONObject("url_model").getString("phone"),
            store.urlModelFile.name
        )
        assertEquals(
            "url_vocab phone name must match model_files.json",
            files.getJSONObject("url_vocab").getString("phone"),
            store.vocabFile.name
        )
        assertEquals(
            "sms_model phone name must match model_files.json",
            files.getJSONObject("sms_model").getString("phone"),
            store.smsModelFile.name
        )
        assertEquals(
            "sms_id_map phone name must match model_files.json",
            files.getJSONObject("sms_id_map").getString("phone"),
            store.idMapFile.name
        )
        assertEquals(
            "sms_vocab phone name must match model_files.json",
            files.getJSONObject("sms_vocab").getString("phone"),
            store.smsVocabFile.name
        )
        assertEquals(
            "sms_tokenizer_dir phone name must match model_files.json",
            files.getJSONObject("sms_tokenizer_dir").getString("phone"),
            store.fileNames.smsTokenizerDir
        )
        assertEquals(
            "llama_model phone name must match model_files.json",
            files.getJSONObject("llama_model").getString("phone"),
            store.llamaModelFile.name
        )
        assertEquals(
            "llama_tokenizer phone name must match model_files.json",
            files.getJSONObject("llama_tokenizer").getString("phone"),
            store.tokenizerFile.name
        )
        assertEquals(
            "sms_fp32 phone name must match model_files.json",
            files.getJSONObject("sms_fp32").getString("phone"),
            store.smsFp32File.name
        )
    }

    @Test
    fun testModelFileNamesDefaultsMatchModelFilesJson() {
        val files = readModelFilesJson().getJSONObject("files")
        val defaults = ModelFileNames.defaults()
        assertEquals(files.getJSONObject("url_model").getString("phone"), defaults.urlModel)
        assertEquals(files.getJSONObject("url_vocab").getString("phone"), defaults.urlVocab)
        assertEquals(files.getJSONObject("sms_model").getString("phone"), defaults.smsModel)
        assertEquals(files.getJSONObject("sms_id_map").getString("phone"), defaults.smsIdMap)
        assertEquals(files.getJSONObject("sms_vocab").getString("phone"), defaults.smsVocab)
        assertEquals(files.getJSONObject("sms_tokenizer_dir").getString("phone"), defaults.smsTokenizerDir)
        assertEquals(files.getJSONObject("llama_model").getString("phone"), defaults.llamaModel)
        assertEquals(files.getJSONObject("llama_tokenizer").getString("phone"), defaults.llamaTokenizer)
        assertEquals(files.getJSONObject("sms_fp32").getString("phone"), defaults.smsFp32)
    }

    @Test
    fun testOptionalPhoneNameSmsFp32MatchesModelFilesJson() {
        val text = readModelFilesText()
        assertEquals(
            "optional sms_fp32 phone name must match model_files.json",
            readModelFilesJson().getJSONObject("files").getJSONObject("sms_fp32").getString("phone"),
            ModelFileNames.optionalPhoneName(text, "sms_fp32")
        )
        assertEquals(
            "absent role returns null",
            null,
            ModelFileNames.optionalPhoneName(text, "sms_fp32_missing")
        )
    }

    @Test
    fun testParsePhoneNamesMatchesModelFilesJson() {
        val text = readModelFilesText()
        val phones = ModelFileNames.parsePhoneNames(text)
        val roles = listOf(
            "url_model", "url_vocab", "sms_model", "sms_id_map",
            "sms_vocab", "sms_tokenizer_dir", "llama_model", "llama_tokenizer"
        )
        assertEquals(roles.size, phones.size)
        for (role in roles) {
            assertTrue("missing role $role", phones.containsKey(role))
            assertEquals(
                "phone name for $role must match model_files.json",
                readModelFilesJson().getJSONObject("files").getJSONObject(role).getString("phone"),
                phones[role]
            )
        }
    }
}
